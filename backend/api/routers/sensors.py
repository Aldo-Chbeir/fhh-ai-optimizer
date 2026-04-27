from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
import asyncpg

from ..db import get_conn
from ..errors import MachineNotFound, SensorNotFound
from ..models import (
    SensorReading, SensorReadingList,
    SensorHistory, SensorHistoryPoint, NormalRange,
    HistoryWindow, HistoryAggregation,
)
from ..services.constants import SENSOR_META, VALID_MACHINE_IDS

router = APIRouter(prefix="/machines/{machine_id}", tags=["maintenance"])

_WINDOW_TO_INTERVAL = {
    "1h": "1 hour",
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
}

_AGG_TO_BUCKET = {
    "raw": None,            # No bucket — return raw points
    "hourly": "1 hour",
    "daily": "1 day",
}


@router.get("/sensors", response_model=SensorReadingList)
async def latest_sensor_readings(
    machine_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> SensorReadingList:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)

    # Latest reading per sensor_type for the machine.
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (sensor_type)
               sensor_type, machine_id, component_id, value, unit, timestamp, is_anomaly
        FROM sensor_readings
        WHERE machine_id = $1
        ORDER BY sensor_type, timestamp DESC
        """,
        machine_id,
    )

    readings: list[SensorReading] = []
    last_ts: datetime | None = None
    for r in rows:
        readings.append(SensorReading(
            sensor_type=r["sensor_type"],
            machine_id=r["machine_id"],
            component_id=r["component_id"],
            value=float(r["value"]),
            unit=r["unit"],
            timestamp=r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            is_anomaly=bool(r["is_anomaly"]),
        ))
        if last_ts is None or r["timestamp"] > last_ts:
            last_ts = r["timestamp"]

    last_iso = (
        last_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if last_ts else
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    return SensorReadingList(
        machine_id=machine_id,
        readings=readings,
        last_updated=last_iso,
    )


@router.get("/sensors/{sensor_type}/history", response_model=SensorHistory)
async def sensor_history(
    machine_id: str,
    sensor_type: str,
    window: HistoryWindow = Query(HistoryWindow.H24),
    aggregation: HistoryAggregation = Query(HistoryAggregation.HOURLY),
    conn: asyncpg.Connection = Depends(get_conn),
) -> SensorHistory:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)
    meta = SENSOR_META.get(sensor_type)
    if meta is None:
        raise SensorNotFound(sensor_type)
    _comp, unit, n_min, n_max = meta

    interval = _WINDOW_TO_INTERVAL[window.value]
    bucket = _AGG_TO_BUCKET[aggregation.value]

    points: list[SensorHistoryPoint] = []
    if bucket is None:
        rows = await conn.fetch(
            f"""
            SELECT timestamp, value
            FROM sensor_readings
            WHERE machine_id = $1
              AND sensor_type = $2
              AND timestamp > NOW() - INTERVAL '{interval}'
            ORDER BY timestamp ASC
            LIMIT 5000
            """,
            machine_id, sensor_type,
        )
        for r in rows:
            ts = r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            points.append(SensorHistoryPoint(
                timestamp=ts, value=float(r["value"]), min=None, max=None,
            ))
    else:
        rows = await conn.fetch(
            f"""
            SELECT
                time_bucket(INTERVAL '{bucket}', timestamp) AS bucket_ts,
                AVG(value)::float AS avg_v,
                MIN(value)::float AS min_v,
                MAX(value)::float AS max_v
            FROM sensor_readings
            WHERE machine_id = $1
              AND sensor_type = $2
              AND timestamp > NOW() - INTERVAL '{interval}'
            GROUP BY bucket_ts
            ORDER BY bucket_ts ASC
            """,
            machine_id, sensor_type,
        )
        for r in rows:
            ts = r["bucket_ts"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            points.append(SensorHistoryPoint(
                timestamp=ts,
                value=round(float(r["avg_v"]), 4),
                min=round(float(r["min_v"]), 4),
                max=round(float(r["max_v"]), 4),
            ))

    return SensorHistory(
        machine_id=machine_id,
        sensor_type=sensor_type,
        unit=unit,
        window=window.value,
        aggregation=aggregation.value,
        normal_range=NormalRange(min=n_min, max=n_max),
        points=points,
    )
