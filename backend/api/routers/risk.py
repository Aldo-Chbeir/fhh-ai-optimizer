from __future__ import annotations

from fastapi import APIRouter, Depends
import asyncpg

from ..db import get_conn
from ..errors import ComponentNotFound, MachineNotFound
from ..models import (
    RiskScore, ComponentRiskScore, SensorContribution,
    PredictionList, Prediction,
)
from ..services.constants import VALID_COMPONENT_IDS, VALID_MACHINE_IDS
from ..services.risk import (
    component_risk, component_risk_full, machine_risk,
    top_contributing_sensors, now_iso,
)
from ..services.predictions import predictions_for_machine

router = APIRouter(prefix="/machines/{machine_id}", tags=["maintenance"])


@router.get("/risk-score", response_model=RiskScore)
async def get_machine_risk_score(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> RiskScore:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    score, tier, worst = await machine_risk(conn, machine_id)
    return RiskScore(
        machine_id=machine_id,
        score=score,
        tier=tier,
        highest_risk_component_id=worst,
        last_updated=now_iso(),
    )


@router.get(
    "/components/{component_id}/risk-score",
    response_model=ComponentRiskScore,
)
async def get_component_risk_score(
    machine_id: str,
    component_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> ComponentRiskScore:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    if component_id not in VALID_COMPONENT_IDS:
        raise ComponentNotFound(machine_id, component_id)

    exists = await conn.fetchval(
        """
        SELECT 1 FROM components
        WHERE machine_id = $1 AND component_id = $2
        """,
        machine_id, component_id,
    )
    if not exists:
        raise ComponentNotFound(machine_id, component_id)

    # Single full inference call covers score, tier, window, AND
    # contributing-feature ranking — saves a second model load.
    payload = await component_risk_full(conn, machine_id, component_id)
    contributions = await top_contributing_sensors(conn, machine_id, component_id)
    return ComponentRiskScore(
        machine_id=machine_id,
        component_id=component_id,
        score=payload["score"],
        tier=payload["tier"],
        predicted_failure_window_hours=payload["predicted_failure_window_hours"],
        top_contributing_sensors=[SensorContribution(**c) for c in contributions],
        last_updated=payload.get("as_of") or now_iso(),
    )


@router.get("/predictions", response_model=PredictionList)
async def get_predictions(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> PredictionList:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    preds = await predictions_for_machine(conn, machine_id)
    return PredictionList(
        machine_id=machine_id,
        predictions=[Prediction(**p) for p in preds],
        generated_at=now_iso(),
    )
