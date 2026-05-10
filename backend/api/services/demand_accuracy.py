"""Forecast-accuracy report for one (market, sku) over the trailing window.

Strategy:
  - If a trained Prophet model exists for this pair AND we have actuals in
    `demand_history` overlapping the requested window, run the model on those
    dates and build the report from real predictions vs real actuals.
  - Otherwise (the seed DB ships with no demand_history rows and no Prophet
    pkls), synthesize a plausible report deterministically from (sku, market,
    date). This is the path the demo runs on; the synthetic series targets
    ~10% MAPE and ~88% confidence-band coverage so the modal looks realistic.

Both paths return the same shape — see `accuracy_report()` below.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Pull baselines from the existing synthetic forecaster so the actuals scale
# matches what the rest of the Demand tab shows for the same (market, sku).
from .forecast import _CATEGORY_BASELINE, _MARKET_MULTIPLIER, _YEARLY_INDEX

TARGET_COVERAGE_PCT = 80.0


def _det_rand(*parts: str) -> float:
    """Deterministic float in [0, 1) from a string tuple."""
    h = hashlib.sha1("|".join(parts).encode()).digest()
    return int.from_bytes(h[:6], "big") / float(1 << 48)


def _baseline_daily(sku: str, category: Optional[str], market: str) -> float:
    monthly = _CATEGORY_BASELINE.get(category or "", 50_000)
    monthly *= _MARKET_MULTIPLIER.get(market, 1.0)
    return monthly / 30.0


# ---------------------------------------------------------------------------
# Synthetic path — DEMO: synthesized accuracy data — replace when historical
# forecasts persist (or when demand_history gets seeded and Prophet models
# land in models/demand/).
# ---------------------------------------------------------------------------

def _synth_actual(sku: str, market: str, d: date, baseline: float) -> int:
    """A plausible daily 'actual' demand reading."""
    yearly = _YEARLY_INDEX[d.month - 1]
    # Thu/Fri/Sat are higher-volume retail days in MENA
    wd = d.weekday()  # 0=Mon..6=Sun
    weekly = 1.07 if wd in (3, 4, 5) else (0.94 if wd == 0 else 1.0)
    noise = 0.92 + 0.16 * _det_rand(sku, market, d.isoformat(), "actual")
    return max(0, int(round(baseline * yearly * weekly * noise)))


def _synth_forecast(sku: str, market: str, d: date, actual: int) -> tuple[int, int, int]:
    """Forecast point + (lower, upper) band for one day.

    Targets:
      - per-day forecast vs actual error ~ U[-18 %, +18 %] → MAPE ~ 9 %
      - band half-width = 15 % of `actual` (symmetric around the truth, not
        around yhat — this keeps above-band and below-band miss counts
        roughly even, matching what a well-calibrated model would show).
        Coverage lands ~85-90 %.
    """
    err = (_det_rand(sku, market, d.isoformat(), "fc") - 0.5) * 0.36  # ±18 %
    yhat = max(0, int(round(actual * (1 + err))))
    half = int(round(actual * 0.15))
    return yhat, max(0, yhat - half), yhat + half


def _synth_report(
    sku: str, market: str, category: Optional[str], days: int, end: date,
) -> dict:
    baseline = _baseline_daily(sku, category, market)
    daily: list[dict] = []
    within = above = below = 0
    abs_pct_err_sum = 0.0
    abs_pct_err_n = 0

    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        actual = _synth_actual(sku, market, d, baseline)
        yhat, lo, hi = _synth_forecast(sku, market, d, actual)
        in_band = lo <= actual <= hi
        if in_band:
            within += 1
        elif actual > hi:
            above += 1
        else:
            below += 1
        if actual > 0:
            abs_pct_err_sum += abs(yhat - actual) / actual
            abs_pct_err_n += 1
        daily.append({
            "date": d.isoformat(),
            "actual": actual,
            "forecast": yhat,
            "yhat_lower": lo,
            "yhat_upper": hi,
            "in_band": in_band,
        })

    coverage_pct = round(100.0 * within / max(1, len(daily)), 1)
    mape = round(100.0 * abs_pct_err_sum / max(1, abs_pct_err_n), 1)

    return {
        "market": market,
        "sku": sku,
        "period_days": days,
        "mape": mape,
        "confidence_coverage": {
            "total_observations": len(daily),
            "within_band": within,
            "above_band": above,
            "below_band": below,
            "coverage_pct": coverage_pct,
            "target_pct": TARGET_COVERAGE_PCT,
        },
        "daily": daily,
        "model": "synthetic",
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Prophet path — uses real actuals from demand_history vs in-window predictions
# ---------------------------------------------------------------------------

def _prophet_report(sku: str, market: str, days: int, end: date) -> Optional[dict]:
    """Return a real accuracy report if a Prophet model + actuals are both
    available, else None so the caller falls back to synthesis."""
    try:
        from backend.demand_ml import config as dconf, data as ddata, persist
        if not persist.exists(dconf.model_path(market, sku)):
            return None
        hist = ddata.load_market_product_history(market, sku)
        if hist.empty:
            return None
    except Exception:
        return None

    import numpy as np
    import pandas as pd

    start = end - timedelta(days=days - 1)
    window = hist[
        (hist["ds"] >= pd.Timestamp(start)) & (hist["ds"] <= pd.Timestamp(end))
    ].copy()
    if window.empty:
        return None

    artifact = persist.load(dconf.model_path(market, sku))
    model = artifact["model"]
    future = window[["ds"] + dconf.REGRESSORS].copy()
    forecast = model.predict(future)

    y_true = window["y"].to_numpy()
    yhat = forecast["yhat"].to_numpy()
    lo = forecast["yhat_lower"].to_numpy()
    hi = forecast["yhat_upper"].to_numpy()
    in_band = (y_true >= lo) & (y_true <= hi)

    safe_y = np.where(y_true == 0, 1.0, y_true)
    mape = float(np.mean(np.abs(yhat - y_true) / np.abs(safe_y)) * 100.0)

    daily = [
        {
            "date": pd.Timestamp(window["ds"].iloc[i]).strftime("%Y-%m-%d"),
            "actual": int(round(float(y_true[i]))),
            "forecast": int(round(float(yhat[i]))),
            "yhat_lower": int(round(float(lo[i]))),
            "yhat_upper": int(round(float(hi[i]))),
            "in_band": bool(in_band[i]),
        }
        for i in range(len(window))
    ]
    within = int(in_band.sum())
    above = int(((y_true > hi)).sum())
    below = int(((y_true < lo)).sum())

    return {
        "market": market,
        "sku": sku,
        "period_days": days,
        "mape": round(mape, 1),
        "confidence_coverage": {
            "total_observations": len(daily),
            "within_band": within,
            "above_band": above,
            "below_band": below,
            "coverage_pct": round(100.0 * within / len(daily), 1),
            "target_pct": TARGET_COVERAGE_PCT,
        },
        "daily": daily,
        "model": "prophet",
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def accuracy_report(
    sku: str, market: str, days: int, category: Optional[str] = None,
    end_date: Optional[date] = None,
) -> dict:
    end = end_date or date.today()
    real = _prophet_report(sku, market, days, end)
    if real is not None:
        return real
    return _synth_report(sku, market, category, days, end)
