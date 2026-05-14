from __future__ import annotations

from fastapi import APIRouter, Depends
import asyncpg

from ..db import get_conn
from ..errors import MachineNotFound
from ..models import Machine, MachineList
from ..services.alerts import count_active_buckets_for_machine
from ..services.constants import VALID_MACHINE_IDS
from ..services.risk import machine_risk

router = APIRouter(prefix="/machines", tags=["maintenance"])


async def _machine_object(conn: asyncpg.Connection, machine_id: str) -> dict:
    row = await conn.fetchrow(
        """
        SELECT machine_id, name, location, model, installation_date,
               status, current_speed_mpm, current_oee_percent
        FROM machines
        WHERE machine_id = $1
        """,
        machine_id,
    )
    if row is None:
        raise MachineNotFound(machine_id)
    score, tier, _ = await machine_risk(conn, machine_id)
    # F2-cleaned bucket count — must equal the "Active" tab on the
    # Alerts page when filtered to this machine. See
    # services.alerts.count_active_buckets_for_machine for rationale.
    active = await count_active_buckets_for_machine(conn, machine_id)
    return {
        "machine_id": row["machine_id"],
        "name": row["name"],
        "location": row["location"],
        "model": row["model"],
        "installation_date": row["installation_date"].isoformat(),
        "status": row["status"],
        "current_speed_mpm": int(row["current_speed_mpm"]),
        "current_oee_percent": float(row["current_oee_percent"]),
        "risk_score": score,
        "risk_tier": tier,
        "active_alerts_count": int(active),
    }


@router.get("", response_model=MachineList)
async def list_machines(conn: asyncpg.Connection = Depends(get_conn)) -> MachineList:
    rows = await conn.fetch(
        "SELECT machine_id FROM machines ORDER BY machine_id"
    )
    machines = [
        Machine(**(await _machine_object(conn, r["machine_id"]))) for r in rows
    ]
    return MachineList(machines=machines, total=len(machines))


@router.get("/{machine_id}", response_model=Machine)
async def get_machine(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> Machine:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    return Machine(**(await _machine_object(conn, machine_id)))
