"""Demand forecast service.

There is no forecast table in the seed DB yet — forecasts are synthesised
deterministically from a (sku, market) seed combined with a seasonality
curve. This stays stable across calls without depending on a real model.
The shape matches API_CONTRACT.md v1.1 exactly.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .constants import VALID_MARKET_IDS

# Average monthly volume baseline by SKU category, modulated by market.
_CATEGORY_BASELINE = {
    "tissue":     140_000,
    "baby_care":   80_000,
    "adult_care":  35_000,
    "fine_guard":  60_000,
    "wellness":    45_000,
    "cosmetics":   25_000,
}

_MARKET_MULTIPLIER = {
    "uae":     1.10,
    "ksa":     1.30,
    "egypt":   0.95,
    "jordan":  0.85,
    "morocco": 0.90,
}

# Yearly seasonality index (1.0 = average) by month, common to MENA tissue
# demand: peaks in Ramadan/Eid window, dip in summer.
_YEARLY_INDEX = [
    0.92, 0.95, 1.20, 1.15, 1.00, 0.85,
    0.82, 0.85, 0.95, 1.02, 1.05, 1.10,
]

_REGRESSORS = ["historical_sales", "ramadan_calendar", "b2b_pipeline"]


def _seed_for(sku: str, market: str) -> int:
    h = hashlib.sha1(f"{sku}|{market}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def _baseline_for(sku: str, category: Optional[str], market: str) -> float:
    base = _CATEGORY_BASELINE.get(category or "", 50_000)
    mult = _MARKET_MULTIPLIER.get(market, 1.0)
    return base * mult


def _month_iter(start: date, n: int):
    y, m = start.year, start.month
    for _ in range(n):
        yield date(y, m, 1)
        m += 1
        if m > 12:
            m = 1
            y += 1


def _ramadan_events(start: date, horizon_months: int) -> list[dict]:
    """Static seasonality events the contract example shows."""
    out = []
    if start <= date(2026, 3, 10) <= start + timedelta(days=30 * horizon_months):
        out.append({
            "date": "2026-03-10", "label": "Ramadan begins", "expected_lift_percent": 35.0,
        })
    if start <= date(2026, 4, 9) <= start + timedelta(days=30 * horizon_months):
        out.append({
            "date": "2026-04-09", "label": "Eid al-Fitr", "expected_lift_percent": 22.0,
        })
    return out


def build_forecast(
    sku: str,
    market: str,
    horizon_months: int = 6,
    category: Optional[str] = None,
) -> dict:
    if market not in VALID_MARKET_IDS:
        raise ValueError(f"unknown market '{market}'")

    rng = random.Random(_seed_for(sku, market))
    baseline = _baseline_for(sku, category, market)

    # Anchor "today" — start the forecast from the current month.
    today = date.today()
    if today.year < 2026:
        today = date(2026, 4, 25)
    start = date(today.year, today.month, 1) + timedelta(days=32)
    start = date(start.year, start.month, 1)

    points: list[dict] = []
    for d in _month_iter(start, horizon_months):
        idx = _YEARLY_INDEX[d.month - 1]
        # Slight noise so each month differs.
        noise = 1.0 + (rng.random() - 0.5) * 0.04
        val = baseline * idx * noise
        # ±10% confidence band, widening with horizon.
        widen = 1.0 + 0.005 * len(points)
        lower = val * (1.0 - 0.10 * widen)
        upper = val * (1.0 + 0.10 * widen)
        points.append({
            "date": d.isoformat(),
            "forecast_value": int(round(val)),
            "lower_bound":    int(round(lower)),
            "upper_bound":    int(round(upper)),
        })

    return {
        "sku": sku,
        "market": market,
        "horizon_months": horizon_months,
        "model": "prophet",
        "forecast": points,
        "seasonality_events": _ramadan_events(start, horizon_months),
        "regressors_used": _REGRESSORS,
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def apply_scenario(
    base: list[dict],
    scenario_type: str,
    magnitude_percent: float,
    event: Optional[str] = None,
) -> list[dict]:
    """Mutate the baseline forecast based on the scenario type."""
    out: list[dict] = []
    for p in base:
        d = date.fromisoformat(p["date"])
        delta_factor = 1.0
        if scenario_type == "seasonality_shift":
            # Apply the lift on the months that match the event window.
            if (event or "").lower() == "ramadan" and d.month in (3, 4):
                delta_factor = 1.0 + magnitude_percent / 100.0
            elif event:
                delta_factor = 1.0 + (magnitude_percent / 100.0) * 0.5
        elif scenario_type == "price_change":
            # Demand elasticity ≈ -1.2 by default
            delta_factor = 1.0 - 0.012 * magnitude_percent
        elif scenario_type == "competitor_entry":
            delta_factor = 1.0 - magnitude_percent / 100.0
        elif scenario_type == "supply_disruption":
            delta_factor = 1.0 - magnitude_percent / 100.0

        out.append({
            "date": p["date"],
            "forecast_value": int(round(p["forecast_value"] * delta_factor)),
            "lower_bound":    int(round(p["lower_bound"]    * delta_factor)),
            "upper_bound":    int(round(p["upper_bound"]    * delta_factor)),
        })
    return out


def seasonality_for(sku: str, market: Optional[str] = None) -> dict:
    pattern = [
        {"month": i + 1, "index": round(_YEARLY_INDEX[i], 2)} for i in range(12)
    ]
    events = [
        {"name": "ramadan",        "average_lift_percent": 35.0},
        {"name": "eid_al_fitr",    "average_lift_percent": 22.0},
        {"name": "back_to_school", "average_lift_percent": 12.0},
    ]
    return {
        "sku": sku,
        "market": market,
        "yearly_pattern": pattern,
        "events": events,
    }
