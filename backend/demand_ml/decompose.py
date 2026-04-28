"""Forecast decomposition — pulls trend / weekly / yearly / regressor curves
out of a fitted Prophet model so the frontend's "show your work" panel can
explain which signal drove which lift.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from . import config


def decompose_forecast_frame(forecast: pd.DataFrame) -> dict[str, list]:
    """Take Prophet's `predict()` output frame and slice out the named components.

    Prophet emits one column per regressor when `add_regressor` is used —
    we sum them under the umbrella `holiday_component`.

    Returns:
        {
          "trend":     [{"date": "2026-04-25", "value": 142000.0}, ...],
          "weekly":    [{"day": "Mon", "value": -0.05}, ..., {"day": "Sun", ...}],
          "yearly":    [{"day_of_year": 1, "value": ...}, ...],
          "regressors": {
             "is_ramadan":              [{"date": ..., "lift_pct": ...}],
             "is_eid_alfitr":           [...],
             ...
          }
        }
    """
    out: dict[str, list | dict] = {}

    # Trend (Prophet exposes both `trend` and `yhat`)
    if "trend" in forecast:
        out["trend"] = [
            {"date": pd.Timestamp(t).strftime("%Y-%m-%d"), "value": round(float(v), 2)}
            for t, v in zip(forecast["ds"], forecast["trend"])
        ]
    else:
        out["trend"] = []

    # Weekly seasonality, in [Mon..Sun] order
    if "weekly" in forecast:
        weekly_avg = (
            forecast.assign(weekday=forecast["ds"].dt.dayofweek)
                    .groupby("weekday")["weekly"].mean()
        )
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        out["weekly"] = [
            {"day": days[i], "value": round(float(weekly_avg.get(i, 0.0)), 4)}
            for i in range(7)
        ]
    else:
        out["weekly"] = []

    # Yearly seasonality — one value per day-of-year (median across rows)
    if "yearly" in forecast:
        yearly_df = (
            forecast.assign(doy=forecast["ds"].dt.dayofyear)
                    .groupby("doy")["yearly"].median()
                    .reset_index()
        )
        out["yearly"] = [
            {"day_of_year": int(r.doy), "value": round(float(r.yearly), 4)}
            for r in yearly_df.itertuples()
        ]
    else:
        out["yearly"] = []

    # Per-regressor multiplicative lifts
    reg_out: dict[str, list] = {}
    for r in config.REGRESSORS:
        if r in forecast:
            # Multiplicative regressors come back as multipliers; convert to %.
            lifts = [
                {"date": pd.Timestamp(t).strftime("%Y-%m-%d"),
                 "lift_pct": round(float(v) * 100.0, 2)}
                for t, v in zip(forecast["ds"], forecast[r])
                if abs(float(v)) > 1e-6
            ]
            if lifts:
                reg_out[r] = lifts
    out["regressors"] = reg_out
    return out
