"""Inference pipeline used by the API and the validation harness.

Public:
    forecast_demand(market_id, product_id, horizon_days=90, scenario_overrides=None)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

from . import MODEL_VERSION, config, data, decompose, persist

log = logging.getLogger("fhh.demand.predict")


# ---------------------------------------------------------------------------
# Lazy model loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _load_model_artifact(market_id: str, product_id: str) -> dict:
    return persist.load(config.model_path(market_id, product_id))


def reset_caches() -> None:
    _load_model_artifact.cache_clear()


def model_exists(market_id: str, product_id: str) -> bool:
    return persist.exists(config.model_path(market_id, product_id))


# ---------------------------------------------------------------------------
# Scenario overrides
# ---------------------------------------------------------------------------

def _apply_scenario(future_regressors: pd.DataFrame, scenario_overrides: dict) -> pd.DataFrame:
    """Mutate the future-frame regressor columns according to a scenario dict.

    Supported keys (extensible):
      - is_ramadan_starts_earlier: int  → shift Ramadan/pre-stockup flags earlier by N days
      - ramadan_intensity_multiplier: float → scale is_ramadan numeric weight (e.g. 1.5 → +50% lift)
      - promo_boost: float               → set promo_active to this fraction of future days
      - eid_alfitr_extra_day: bool       → flag the day BEFORE Eid as an extra Eid day too
      - disable_ramadan: bool            → zero out Ramadan & pre-stockup flags
    """
    df = future_regressors.copy()
    if not scenario_overrides:
        return df

    if int(scenario_overrides.get("is_ramadan_starts_earlier", 0)):
        shift = int(scenario_overrides["is_ramadan_starts_earlier"])
        for col in ("is_ramadan", "is_pre_ramadan_stockup"):
            df[col] = df[col].shift(-shift, fill_value=0).astype(int)

    if scenario_overrides.get("disable_ramadan"):
        df["is_ramadan"] = 0
        df["is_pre_ramadan_stockup"] = 0

    if scenario_overrides.get("ramadan_intensity_multiplier") is not None:
        # Multiplicative regressor: Prophet computes
        #     yhat = trend × (1 + Σ multiplicative_effects)
        # so scaling the regressor column above 1 amplifies the learned lift
        # proportionally. We DON'T round to int — Prophet accepts floats.
        m = float(scenario_overrides["ramadan_intensity_multiplier"])
        df["is_ramadan"] = df["is_ramadan"].astype(float) * m
        df["is_pre_ramadan_stockup"] = df["is_pre_ramadan_stockup"].astype(float) * m

    if scenario_overrides.get("promo_boost") is not None:
        frac = float(scenario_overrides["promo_boost"])
        n = len(df)
        n_promo = int(round(n * frac))
        if n_promo:
            # Distribute promo days uniformly across the horizon.
            stride = max(1, n // n_promo)
            promo_idx = np.arange(0, n, stride)[:n_promo]
            df.loc[promo_idx, "promo_active"] = 1

    if scenario_overrides.get("eid_alfitr_extra_day"):
        # Tag the day before each Eid as Eid too.
        eid_idx = df.index[df["is_eid_alfitr"] == 1]
        for i in eid_idx:
            if i - 1 >= 0:
                df.at[i - 1, "is_eid_alfitr"] = 1

    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_history_date(market_id: str, product_id: str) -> date:
    """Most recent `ds` we have actuals for (the seeder ends Dec 31 2025)."""
    df = data.load_market_product_history(market_id, product_id)
    if df.empty:
        return date.today()
    return pd.Timestamp(df["ds"].max()).date()


def _trend_direction(forecast_df: pd.DataFrame) -> str:
    if "trend" not in forecast_df:
        return "flat"
    a = float(forecast_df["trend"].iloc[0])
    b = float(forecast_df["trend"].iloc[-1])
    pct = 100.0 * (b - a) / max(abs(a), 1.0)
    if pct > 1.0:
        return "up"
    if pct < -1.0:
        return "down"
    return "flat"


def _weekly_rollup(forecast_df: pd.DataFrame) -> list[dict]:
    df = forecast_df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    df["week_start"] = df["ds"].dt.to_period("W-MON").dt.start_time
    g = df.groupby("week_start").agg(
        total_predicted=("yhat", "sum"),
        total_lower=("yhat_lower", "sum"),
        total_upper=("yhat_upper", "sum"),
    ).reset_index()
    return [
        {
            "week_start_date": pd.Timestamp(r.week_start).strftime("%Y-%m-%d"),
            "total_predicted": int(round(float(r.total_predicted))),
            "total_lower":     int(round(float(r.total_lower))),
            "total_upper":     int(round(float(r.total_upper))),
        }
        for r in g.itertuples()
    ]


def _monthly_rollup(forecast_df: pd.DataFrame) -> list[dict]:
    df = forecast_df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    df["month"] = df["ds"].dt.to_period("M").dt.start_time
    g = df.groupby("month").agg(
        total_predicted=("yhat", "sum"),
        total_lower=("yhat_lower", "sum"),
        total_upper=("yhat_upper", "sum"),
    ).reset_index()
    return [
        {
            "month": pd.Timestamp(r.month).strftime("%Y-%m-%d"),
            "total_predicted": int(round(float(r.total_predicted))),
            "total_lower":     int(round(float(r.total_lower))),
            "total_upper":     int(round(float(r.total_upper))),
        }
        for r in g.itertuples()
    ]


def _key_drivers(
    forecast_df: pd.DataFrame, history_df: pd.DataFrame,
) -> dict[str, float | str]:
    """Surface high-level drivers for the dashboard's "why this number" card."""
    drivers: dict[str, float | str] = {
        "yoy_growth_pct": 0.0,
        "ramadan_lift_pct": 0.0,
        "eid_alfitr_lift_pct": 0.0,
        "summer_dip_pct": 0.0,
        "trend_direction": _trend_direction(forecast_df),
    }

    # Forecast vs same-period-last-year actuals (units sum)
    if not history_df.empty:
        forecast_total = float(forecast_df["yhat"].sum())
        first_ds = pd.Timestamp(forecast_df["ds"].iloc[0]).date()
        last_ds = pd.Timestamp(forecast_df["ds"].iloc[-1]).date()
        py_lo = first_ds.replace(year=first_ds.year - 1)
        py_hi = last_ds.replace(year=last_ds.year - 1)
        py_slice = history_df[
            (history_df["ds"].dt.date >= py_lo) &
            (history_df["ds"].dt.date <= py_hi)
        ]
        if not py_slice.empty:
            base = float(py_slice["y"].sum())
            if base > 0:
                drivers["yoy_growth_pct"] = round(
                    100.0 * (forecast_total - base) / base, 2
                )

    # Multiplicative regressor lifts → average over rows where flag is on
    for col_name, key in [
        ("is_ramadan", "ramadan_lift_pct"),
        ("is_eid_alfitr", "eid_alfitr_lift_pct"),
    ]:
        if col_name in forecast_df:
            on = forecast_df[forecast_df[col_name] != 0][col_name]
            if not on.empty:
                drivers[key] = round(float(on.mean()) * 100.0, 2)

    # Summer dip = how far July-August yhat sits below the rest of the horizon mean
    df = forecast_df.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    summer = df[df["ds"].dt.month.isin([7, 8])]["yhat"].mean()
    rest = df[~df["ds"].dt.month.isin([7, 8])]["yhat"].mean()
    if rest and summer:
        drivers["summer_dip_pct"] = round(100.0 * (summer - rest) / rest, 2)

    return drivers


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def forecast_demand(
    market_id: str,
    product_id: str,
    horizon_days: int = config.DEFAULT_HORIZON_DAYS,
    scenario_overrides: Optional[dict] = None,
) -> dict:
    """Run a forward forecast for a single (market, sku)."""
    artifact = _load_model_artifact(market_id, product_id)
    model = artifact["model"]
    trained_until = artifact.get("trained_until", str(config.TRAIN_END))

    last_hist = _last_history_date(market_id, product_id)
    future_regressors = data.build_future_frame(last_hist, horizon_days)
    future_regressors = _apply_scenario(future_regressors, scenario_overrides or {})

    raw_forecast = model.predict(future_regressors)

    # Build the per-day forecast points
    forecast_points: list[dict] = []
    for r in raw_forecast.itertuples():
        forecast_points.append({
            "date": pd.Timestamp(r.ds).strftime("%Y-%m-%d"),
            "predicted_units": int(round(float(r.yhat))),
            "lower_bound":     int(round(float(r.yhat_lower))),
            "upper_bound":     int(round(float(r.yhat_upper))),
            "trend_component": float(round(float(r.trend), 2)) if hasattr(r, "trend") else None,
            "seasonal_component": float(round(
                (float(getattr(r, "weekly", 0)) + float(getattr(r, "yearly", 0))), 4
            )),
            "holiday_component": float(round(
                sum(float(getattr(r, k, 0)) for k in config.REGRESSORS), 4
            )),
        })

    history = data.load_market_product_history(market_id, product_id)

    return {
        "market_id": market_id,
        "product_id": product_id,
        "horizon_days": horizon_days,
        "model": "prophet",
        "model_version": MODEL_VERSION,
        "trained_on_period": {
            "start": str(config.HISTORY_START),
            "end": trained_until,
        },
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast": forecast_points,
        "weekly_rollup": _weekly_rollup(raw_forecast),
        "monthly_rollup": _monthly_rollup(raw_forecast),
        "key_drivers": _key_drivers(raw_forecast, history),
        "regressors_used": list(config.REGRESSORS),
        "scenario_overrides": scenario_overrides or {},
    }


# ---------------------------------------------------------------------------
# Decomposition entrypoint (used by /demand/seasonality)
# ---------------------------------------------------------------------------

def decompose_history(
    market_id: str,
    product_id: str,
    horizon_days: int = 365,
) -> dict:
    """Run a 1-year forward predict and decompose components for the UI."""
    artifact = _load_model_artifact(market_id, product_id)
    model = artifact["model"]
    last_hist = _last_history_date(market_id, product_id)
    future = data.build_future_frame(last_hist, horizon_days)
    forecast_df = model.predict(future)
    return decompose.decompose_forecast_frame(forecast_df)
