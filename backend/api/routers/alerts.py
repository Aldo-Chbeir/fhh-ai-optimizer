from __future__ import annotations

from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
import asyncpg

from ..db import get_conn
from ..errors import AlertNotFound, MachineNotFound
from ..models import (
    Alert, AlertList, AlarmList, Alarm,
    MaintenanceLogList, MaintenanceLogEntry,
    AlarmSeverity, AlertSort,
)
from ..services.alerts import list_alerts, get_alert
from ..services.constants import VALID_MACHINE_IDS

router = APIRouter(tags=["maintenance"])


# -----------------------------------------------------------------------------
# Cross-machine alert endpoints
# -----------------------------------------------------------------------------

@router.get("/alerts", response_model=AlertList)
async def get_alerts(
    severity: Optional[AlarmSeverity] = Query(None),
    machine_id: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    sort: AlertSort = Query(AlertSort.SEVERITY),
    limit: Optional[int] = Query(None, ge=1, le=200),
    conn: asyncpg.Connection = Depends(get_conn),
) -> AlertList:
    if machine_id is not None and machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    alerts, counts = await list_alerts(
        conn,
        severity=severity.value if severity else None,
        machine_id=machine_id,
        acknowledged=acknowledged,
        sort=sort.value,
    )
    if limit is not None:
        alerts = alerts[:limit]
    return AlertList(
        alerts=[Alert(**a) for a in alerts],
        total=len(alerts),
        counts_by_tier=counts,
    )


@router.get("/alerts/{alert_id}", response_model=Alert)
async def get_alert_detail(
    alert_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> Alert:
    a = await get_alert(conn, alert_id)
    if a is None:
        raise AlertNotFound(alert_id)
    return Alert(**a)


# -----------------------------------------------------------------------------
# Per-machine alarms (Valmet DNA DCS event stream) and maintenance log
# -----------------------------------------------------------------------------

machine_router = APIRouter(prefix="/machines/{machine_id}", tags=["maintenance"])


@machine_router.get("/alarms", response_model=AlarmList)
async def list_machine_alarms(
    machine_id: str,
    limit: int = Query(50, ge=1, le=500),
    severity: Optional[AlarmSeverity] = Query(None),
    conn: asyncpg.Connection = Depends(get_conn),
) -> AlarmList:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    sql = """
        SELECT alarm_id, timestamp, severity, description, resolved_at, downtime_minutes
        FROM alarm_events
        WHERE machine_id = $1
    """
    params: list = [machine_id]
    if severity:
        params.append(severity.value)
        sql += f" AND severity = ${len(params)}"
    sql += f" ORDER BY timestamp DESC LIMIT ${len(params)+1}"
    params.append(limit)
    rows = await conn.fetch(sql, *params)
    alarms = []
    for r in rows:
        alarms.append(Alarm(
            alarm_id=r["alarm_id"],
            timestamp=r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            severity=r["severity"],
            description=r["description"],
            resolved_at=(
                r["resolved_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if r["resolved_at"] else None
            ),
            downtime_minutes=int(r["downtime_minutes"]),
        ))
    return AlarmList(machine_id=machine_id, alarms=alarms, total=len(alarms))


@machine_router.get("/maintenance-log", response_model=MaintenanceLogList)
async def list_maintenance_log(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> MaintenanceLogList:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    rows = await conn.fetch(
        """
        SELECT log_id, component_id, maintenance_type, date_performed,
               cost_usd, downtime_hours, technician, notes
        FROM maintenance_logs
        WHERE machine_id = $1
        ORDER BY date_performed DESC
        """,
        machine_id,
    )
    logs = [
        MaintenanceLogEntry(
            log_id=r["log_id"],
            component_id=r["component_id"],
            maintenance_type=r["maintenance_type"],
            date_performed=r["date_performed"].isoformat(),
            cost_usd=float(r["cost_usd"]),
            downtime_hours=float(r["downtime_hours"]),
            technician=r["technician"],
            notes=r["notes"],
        )
        for r in rows
    ]
    return MaintenanceLogList(machine_id=machine_id, logs=logs)
