"""Admin endpoints — gated by a static `X-Admin-Token` header for now."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Header, HTTPException, status

log = logging.getLogger("fhh.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_TOKEN_ENV = "ADMIN_TOKEN"
DEFAULT_ADMIN_TOKEN = "fhh-admin-dev-token"


def _check_token(token: str | None) -> None:
    expected = os.getenv(ADMIN_TOKEN_ENV, DEFAULT_ADMIN_TOKEN)
    if not token or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin token",
        )


@router.post("/retrain")
async def retrain(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Trigger a fresh end-to-end training run.

    Steps:
      1. Refit 24 IsolationForest models (per (machine, component)).
      2. Refit the global XGBoost regressor + isotonic calibrator.
      3. Reset the predictor's in-process model cache so subsequent
         requests pick up the new artifacts immediately.

    Returns a summary dict with timing per phase.
    """
    _check_token(x_admin_token)

    def _run_train() -> dict:
        from backend.ml import train_anomaly, train_risk  # noqa: WPS433
        timings: dict[str, float] = {}

        t1 = time.perf_counter()
        train_anomaly.main()
        timings["anomaly_seconds"] = round(time.perf_counter() - t1, 2)

        t2 = time.perf_counter()
        train_risk.main()
        timings["risk_seconds"] = round(time.perf_counter() - t2, 2)

        # Drop cached availability flag + cached loaded artifacts.
        from backend.api.services import risk as risk_service  # noqa: WPS433
        risk_service.reset_ml_cache()

        return timings

    log.info("admin: retrain triggered")
    timings = await asyncio.to_thread(_run_train)
    log.info("admin: retrain finished | %s", timings)

    return {
        "status": "ok",
        "anomaly_seconds": timings["anomaly_seconds"],
        "risk_seconds": timings["risk_seconds"],
        "total_seconds": round(timings["anomaly_seconds"] + timings["risk_seconds"], 2),
    }


@router.post("/retrain-demand")
async def retrain_demand(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Retrain the 185 Prophet demand models.

    Steps:
      1. Re-fit Prophet on every (market, sku) combo using the latest
         `demand_history` rows.
      2. Reset the API's cached "Prophet pipeline available" flag and the
         predictor's loaded-model cache so subsequent /forecast calls pick
         up the freshly persisted models.
    """
    _check_token(x_admin_token)

    def _run() -> dict:
        from backend.demand_ml import train as demand_train  # noqa: WPS433
        t1 = time.perf_counter()
        rc = demand_train.main()
        elapsed = round(time.perf_counter() - t1, 2)
        # Drop cached availability flag + cached predictor models.
        from backend.api.services import demand_prophet  # noqa: WPS433
        demand_prophet.reset_cache()
        return {"return_code": rc, "seconds": elapsed}

    log.info("admin: retrain-demand triggered")
    result = await asyncio.to_thread(_run)
    log.info("admin: retrain-demand finished | %s", result)

    return {
        "status": "ok" if result["return_code"] == 0 else "partial",
        "seconds": result["seconds"],
    }
