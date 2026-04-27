from __future__ import annotations

from fastapi import APIRouter, Depends
import asyncpg

from ..db import get_conn
from ..errors import ComponentNotFound, MachineNotFound
from ..models import Component, ComponentList
from ..services.constants import (
    COMPONENT_ORDER, VALID_COMPONENT_IDS, VALID_MACHINE_IDS,
)
from ..services.risk import component_risk

router = APIRouter(prefix="/machines/{machine_id}", tags=["maintenance"])


@router.get("/components", response_model=ComponentList)
async def list_components(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> ComponentList:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)

    rows = await conn.fetch(
        """
        SELECT component_id, machine_id, name, is_critical,
               expected_lifetime_hours, hours_since_last_maintenance,
               last_maintenance_date
        FROM components
        WHERE machine_id = $1
        """,
        machine_id,
    )
    by_id = {r["component_id"]: r for r in rows}
    components: list[Component] = []
    for cid in COMPONENT_ORDER:
        r = by_id.get(cid)
        if not r:
            continue
        score, tier, _win = await component_risk(conn, machine_id, cid)
        components.append(Component(
            component_id=r["component_id"],
            machine_id=r["machine_id"],
            name=r["name"],
            is_critical=bool(r["is_critical"]),
            risk_score=score,
            risk_tier=tier,
            expected_lifetime_hours=int(r["expected_lifetime_hours"]),
            hours_since_last_maintenance=int(r["hours_since_last_maintenance"]),
            last_maintenance_date=r["last_maintenance_date"].isoformat()
                if r["last_maintenance_date"] else None,
        ))
    return ComponentList(machine_id=machine_id, components=components)
