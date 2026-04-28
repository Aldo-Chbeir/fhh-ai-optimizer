"""Bridge between the FastAPI demand router and the Prophet pipeline.

When trained models exist on disk, the router uses these helpers and returns
real Prophet predictions. Otherwise the router falls back to the synthetic
generator in `services/forecast.py`. The bridge is intentionally tiny — the
heavy lifting lives in `backend.demand_ml`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("fhh.api.demand_prophet")

_PIPELINE_OK: Optional[bool] = None


def _pipeline_available() -> bool:
    global _PIPELINE_OK
    if _PIPELINE_OK is not None:
        return _PIPELINE_OK
    try:
        from backend.demand_ml import config as dconf  # noqa: WPS433
        # Spot-check: does the canonical demo combo have a saved model?
        ok = dconf.model_path("uae", "fine-facial-100").exists()
    except Exception as exc:  # noqa: BLE001
        log.warning("Prophet pipeline check failed: %s — falling back to synthetic", exc)
        ok = False
    _PIPELINE_OK = ok
    log.info("Prophet pipeline %s", "available" if ok else "NOT available")
    return ok


def reset_cache() -> None:
    """Drop cached availability flag and predictor model cache."""
    global _PIPELINE_OK
    _PIPELINE_OK = None
    try:
        from backend.demand_ml import predict as dm_predict  # noqa: WPS433
        dm_predict.reset_caches()
    except Exception:
        pass


def model_exists(market_id: str, product_id: str) -> bool:
    if not _pipeline_available():
        return False
    try:
        from backend.demand_ml import predict as dm_predict  # noqa: WPS433
        return dm_predict.model_exists(market_id, product_id)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Forecast — daily prediction → monthly rollup → contract Forecast shape
# ---------------------------------------------------------------------------

def _daily_to_monthly_contract_points(monthly_rollup: list[dict]) -> list[dict]:
    """Convert predict.forecast_demand's monthly_rollup into contract ForecastPoints."""
    return [
        {
            "date": m["month"],
            "forecast_value": float(m["total_predicted"]),
            "lower_bound":    float(m["total_lower"]),
            "upper_bound":    float(m["total_upper"]),
        }
        for m in monthly_rollup
    ]


def _seasonality_events_from_drivers(key_drivers: dict, monthly_rollup: list[dict]) -> list[dict]:
    """Surface visible Ramadan/Eid lifts as `seasonality_events` in the
    contract response. Empty when the horizon doesn't cross those events."""
    events: list[dict] = []
    if key_drivers.get("ramadan_lift_pct"):
        events.append({
            "date": monthly_rollup[0]["month"] if monthly_rollup else None,
            "label": "Ramadan demand surge",
            "expected_lift_percent": float(key_drivers["ramadan_lift_pct"]),
        })
    if key_drivers.get("eid_alfitr_lift_pct"):
        events.append({
            "date": monthly_rollup[0]["month"] if monthly_rollup else None,
            "label": "Eid al-Fitr peak",
            "expected_lift_percent": float(key_drivers["eid_alfitr_lift_pct"]),
        })
    return [e for e in events if e["date"] is not None]


async def forecast_contract_shape(
    market_id: str,
    product_id: str,
    horizon_months: int,
    scenario_overrides: Optional[dict] = None,
) -> dict:
    """Return a Prophet forecast in the API_CONTRACT.md `Forecast` shape.

    Daily Prophet output → monthly rollup → contract points.
    """

    def _run() -> dict:
        from backend.demand_ml import predict as dm_predict  # noqa: WPS433
        horizon_days = horizon_months * 31  # over-shoot so we cover the last full month
        return dm_predict.forecast_demand(
            market_id=market_id,
            product_id=product_id,
            horizon_days=horizon_days,
            scenario_overrides=scenario_overrides,
        )

    raw = await asyncio.to_thread(_run)

    monthly = raw["monthly_rollup"][:horizon_months]
    contract_points = _daily_to_monthly_contract_points(monthly)

    return {
        "sku": product_id,
        "market": market_id,
        "horizon_months": horizon_months,
        "model": "prophet",
        "forecast": contract_points,
        "seasonality_events": _seasonality_events_from_drivers(raw["key_drivers"], monthly),
        "regressors_used": raw["regressors_used"],
        "generated_at": raw["generated_at"],
        # Internal extras (not in contract — surfaced when callers want them):
        "_extras": {
            "key_drivers": raw["key_drivers"],
            "weekly_rollup": raw["weekly_rollup"],
            "trained_on_period": raw["trained_on_period"],
            "model_version": raw["model_version"],
        },
    }


# ---------------------------------------------------------------------------
# Decomposition — used by /demand/seasonality
# ---------------------------------------------------------------------------

async def decomposition_for(market_id: str, product_id: str) -> dict:
    """Run Prophet decomposition for one (market, sku)."""

    def _run() -> dict:
        from backend.demand_ml import predict as dm_predict  # noqa: WPS433
        return dm_predict.decompose_history(market_id, product_id, horizon_days=365)

    return await asyncio.to_thread(_run)
