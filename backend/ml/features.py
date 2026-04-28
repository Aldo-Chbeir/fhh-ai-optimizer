"""Feature engineering for the FHH AI Optimizer maintenance models.

Pipeline:
  1. Pull hourly aggregates per (machine, sensor) for a time window.
  2. Pivot into a wide hourly frame keyed on (machine, hour) with one column
     per sensor metric.
  3. Compute rolling statistics, trend slopes, deviation-from-baseline,
     anomaly density at every hour.
  4. Slice that frame at the timestamps we want to score (training samples
     OR a single inference point) and join in per-component metadata
     (hours-since-maintenance, days-since-install).

The same `build_feature_frame` function powers training AND inference,
so the two cannot drift.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from . import config, data


# ---------------------------------------------------------------------------
# Hourly base frame  (machine, hour) → wide columns
# ---------------------------------------------------------------------------

def _component_sensors(component_id: str) -> list[str]:
    base = list(config.COMPONENT_SENSORS.get(component_id, []))
    # qcs is a machine-level signal — append it so every component picks up
    # the global "line health" reading. This lets the model learn correlations
    # like "softness drops when Yankee misbehaves".
    base.extend(config.QCS_SENSORS)
    return base


def load_hourly_wide(
    machine_id: str,
    component_id: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Wide frame: index=hour, columns = '{sensor}__{stat}' for the sensors on this component (+qcs).

    Stats: mean, std, min, max, anomaly_count.
    Hours with no data are forward-filled then back-filled (very few gaps in
    a 5-min telemetry stream).
    """
    sensors = _component_sensors(component_id)
    long = data.fetch_hourly_aggregates(machine_id, sensors, start, end)
    if long.empty:
        return pd.DataFrame()

    # Pivot to wide format
    long["bucket_ts"] = pd.to_datetime(long["bucket_ts"], utc=True)
    pivot = long.pivot_table(
        index="bucket_ts",
        columns="sensor_type",
        values=["mean_v", "std_v", "min_v", "max_v", "anomaly_count"],
        aggfunc="first",
    )
    # Flatten the MultiIndex on columns:
    #   ('mean_v',         'yankee_surface_temp') → 'yankee_surface_temp__mean'
    #   ('anomaly_count',  'yankee_surface_temp') → 'yankee_surface_temp__anomaly_count'
    _STAT_RENAME = {
        "mean_v": "mean", "std_v": "std",
        "min_v": "min", "max_v": "max",
        "anomaly_count": "anomaly_count",
    }
    pivot.columns = [f"{sensor}__{_STAT_RENAME.get(stat, stat)}"
                     for stat, sensor in pivot.columns]
    pivot = pivot.sort_index()
    pivot = pivot.ffill().bfill()
    return pivot


# ---------------------------------------------------------------------------
# Feature derivation
# ---------------------------------------------------------------------------

def _slope(y: np.ndarray) -> float:
    """OLS slope of y over an evenly-spaced index (per-hour units).

    Returns 0 if input is too short or constant.
    """
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=np.float64)
    mx = x.mean()
    my = float(np.nanmean(y))
    denom = float(((x - mx) ** 2).sum())
    if denom == 0.0:
        return 0.0
    num = float(((x - mx) * (y - my)).sum())
    return num / denom


def _zscore_30d(series: pd.Series, end_ts: pd.Timestamp) -> float:
    """Robust z-score of `series.iloc[-1]` vs the prior 30 days."""
    if series.empty:
        return 0.0
    cutoff = end_ts - pd.Timedelta(days=30)
    baseline = series[(series.index >= cutoff) & (series.index < end_ts)]
    if len(baseline) < 24:
        return 0.0
    med = float(np.nanmedian(baseline))
    std = float(np.nanstd(baseline))
    if std == 0.0:
        return 0.0
    return float((series.iloc[-1] - med) / std)


def _build_one_sample(
    wide: pd.DataFrame,
    ts: pd.Timestamp,
    component_id: str,
    component_meta_row: pd.Series,
) -> dict[str, float]:
    """Compute features for a single (machine, component, ts).

    `wide` is the hourly wide frame for this machine/component (with qcs).
    Only data with index < ts is used — strict no-leakage.
    """
    feats: dict[str, float] = {}
    sensors = _component_sensors(component_id)

    # Slice strictly before `ts` to prevent target leakage.
    history = wide[wide.index < ts]
    if history.empty:
        # Synthetic placeholder — model receives all-zero features. This only
        # happens if `ts` is earlier than the data window.
        for s in sensors:
            for w_name in config.ROLLING_WINDOWS:
                feats[f"{s}__roll{w_name}_mean"] = 0.0
                feats[f"{s}__roll{w_name}_std"] = 0.0
            for w_name in config.TREND_WINDOWS:
                feats[f"{s}__slope{w_name}"] = 0.0
            feats[f"{s}__zscore30d"] = 0.0
            feats[f"{s}__anom_density_24h"] = 0.0
        feats["component__hours_since_maint"] = 0.0
        feats["component__days_since_install"] = 0.0
        feats["component__lifetime_pct"] = 0.0
        feats["machine__anom_density_24h"] = 0.0
        return feats

    # Per-sensor features
    for s in sensors:
        mean_col = f"{s}__mean"
        std_col = f"{s}__std"
        anom_col = f"{s}__anomaly_count"
        if mean_col not in history.columns:
            for w_name in config.ROLLING_WINDOWS:
                feats[f"{s}__roll{w_name}_mean"] = 0.0
                feats[f"{s}__roll{w_name}_std"] = 0.0
            for w_name in config.TREND_WINDOWS:
                feats[f"{s}__slope{w_name}"] = 0.0
            feats[f"{s}__zscore30d"] = 0.0
            feats[f"{s}__anom_density_24h"] = 0.0
            continue

        mean_series = history[mean_col]

        # Rolling means/std (look-back from ts)
        for w_name, w_hours in config.ROLLING_WINDOWS.items():
            window = mean_series.iloc[-w_hours:] if w_hours <= len(mean_series) else mean_series
            feats[f"{s}__roll{w_name}_mean"] = float(np.nanmean(window))
            feats[f"{s}__roll{w_name}_std"] = float(np.nanstd(window))

        # Trend slopes
        for w_name, w_hours in config.TREND_WINDOWS.items():
            window = mean_series.iloc[-w_hours:].to_numpy() if w_hours <= len(mean_series) else mean_series.to_numpy()
            feats[f"{s}__slope{w_name}"] = _slope(window)

        # 30-day deviation
        feats[f"{s}__zscore30d"] = _zscore_30d(mean_series, ts)

        # Anomaly density last 24h (from the seeded is_anomaly flag)
        if anom_col in history.columns:
            last_24 = history[anom_col].iloc[-24:]
            feats[f"{s}__anom_density_24h"] = float(last_24.sum())
        else:
            feats[f"{s}__anom_density_24h"] = 0.0

    # Component-level meta
    last_maint = component_meta_row.get("last_maintenance_date")
    install = component_meta_row.get("installation_date")
    lifetime = float(component_meta_row.get("expected_lifetime_hours") or 50000.0)

    if pd.isna(last_maint):
        hours_since = float(component_meta_row.get("hours_since_last_maintenance") or 0.0)
    else:
        hours_since = max(0.0, (ts - last_maint).total_seconds() / 3600.0)
    feats["component__hours_since_maint"] = hours_since

    if pd.isna(install):
        days_since_install = 365.0 * 5.0
    else:
        days_since_install = max(0.0, (ts - install).total_seconds() / 86400.0)
    feats["component__days_since_install"] = days_since_install
    feats["component__lifetime_pct"] = hours_since / lifetime if lifetime else 0.0

    # Machine-wide aggregate anomaly density (sum across ALL columns ending in __anomaly_count)
    anom_cols = [c for c in history.columns if c.endswith("__anomaly_count")]
    if anom_cols:
        feats["machine__anom_density_24h"] = float(history[anom_cols].iloc[-24:].sum().sum())
    else:
        feats["machine__anom_density_24h"] = 0.0

    return feats


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

def build_feature_frame(
    machine_id: str,
    component_id: str,
    timestamps: list[pd.Timestamp],
    components_meta: Optional[pd.DataFrame] = None,
    history_start: Optional[datetime] = None,
    history_end: Optional[datetime] = None,
) -> pd.DataFrame:
    """Compute the feature matrix for a list of timestamps on one (machine, component).

    `timestamps` should be tz-aware UTC pd.Timestamps. `history_start`/`end`
    bound the hourly base frame loaded from the DB; defaults are
    [min(timestamps) - 30d, max(timestamps) + 1h].
    """
    if not timestamps:
        return pd.DataFrame()

    raw_idx = pd.DatetimeIndex(timestamps)
    if raw_idx.tz is None:
        ts_index = raw_idx.tz_localize("UTC")
    else:
        ts_index = raw_idx.tz_convert("UTC")

    if history_start is None:
        history_start = (ts_index.min() - pd.Timedelta(days=30)).to_pydatetime()
    if history_end is None:
        history_end = (ts_index.max() + pd.Timedelta(hours=1)).to_pydatetime()

    wide = load_hourly_wide(machine_id, component_id, history_start, history_end)

    if components_meta is None:
        components_meta = data.fetch_components_meta()
    meta_rows = components_meta[
        (components_meta["machine_id"] == machine_id)
        & (components_meta["component_id"] == component_id)
    ]
    if meta_rows.empty:
        meta_row = pd.Series(dtype=object)
    else:
        meta_row = meta_rows.iloc[0]

    rows: list[dict[str, float]] = []
    for ts in ts_index:
        feats = _build_one_sample(wide, ts, component_id, meta_row)
        feats["machine_id"] = machine_id
        feats["component_id"] = component_id
        feats["timestamp"] = ts
        rows.append(feats)

    return pd.DataFrame(rows)


def days_to_next_failure(
    machine_id: str,
    component_id: str,
    ts: pd.Timestamp,
    failures: pd.DataFrame,
) -> float:
    """Days from `ts` to the next corrective event on this (machine, component).

    Returns float('inf') if there is no future failure in the data window.
    """
    f = failures[
        (failures["machine_id"] == machine_id)
        & (failures["component_id"] == component_id)
        & (failures["failure_ts"] >= ts)
    ]
    if f.empty:
        return float("inf")
    delta = (f["failure_ts"].iloc[0] - ts).total_seconds() / 86400.0
    return float(delta)


def label_for_target(days_to_failure: float, horizon_days: float = config.FAILURE_HORIZON_DAYS) -> float:
    """target = max(0, 100 * (1 - days_to_failure / horizon))   capped at [0, 100]."""
    if not np.isfinite(days_to_failure):
        return 0.0
    val = 100.0 * (1.0 - days_to_failure / horizon_days)
    return float(max(0.0, min(100.0, val)))


_NON_FEATURE_COLS = {
    "machine_id", "component_id", "timestamp", "label", "group",
}


def feature_columns(sample: pd.DataFrame) -> list[str]:
    """Return the ordered list of model feature columns.

    Note: `anomaly_score` IS a feature (it's the per-(machine, component)
    IsolationForest output). It's added to the matrix in train_risk.py.
    """
    return [c for c in sample.columns if c not in _NON_FEATURE_COLS]
