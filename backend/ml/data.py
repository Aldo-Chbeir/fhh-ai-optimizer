"""DB loading helpers used by training & inference.

Training is offline so we use a synchronous SQLAlchemy connection (matches
the seeder's convention). The API path uses asyncpg — but at inference
time the API only calls `predict.predict_component_risk` which loads
features for a single (machine, component, timestamp); that's a small
synchronous query that runs comfortably inside an asyncio event loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.db_url_psycopg2(), future=True, pool_pre_ping=True)
    return _engine


def fetch_data_range() -> tuple[datetime, datetime]:
    """Return (min_ts, max_ts) of the sensor_readings hypertable."""
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM sensor_readings"
        )).one()
    return row.lo, row.hi


def fetch_hourly_aggregates(
    machine_id: str,
    sensors: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Return long-form DataFrame[bucket_ts, sensor_type, mean_v, min_v, max_v, std_v, anomaly_count].

    Aggregates 5-min sensor_readings into 1-hour buckets via TimescaleDB
    `time_bucket`.
    """
    if not sensors:
        return pd.DataFrame(columns=[
            "bucket_ts", "sensor_type", "mean_v", "min_v", "max_v", "std_v", "anomaly_count",
        ])
    sql = """
        SELECT
            time_bucket(INTERVAL '1 hour', timestamp) AS bucket_ts,
            sensor_type,
            AVG(value)::float                         AS mean_v,
            MIN(value)::float                         AS min_v,
            MAX(value)::float                         AS max_v,
            COALESCE(STDDEV_POP(value)::float, 0.0)   AS std_v,
            SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) AS anomaly_count
        FROM sensor_readings
        WHERE machine_id = :m
          AND sensor_type = ANY(:s)
          AND timestamp >= :lo
          AND timestamp <  :hi
        GROUP BY bucket_ts, sensor_type
        ORDER BY bucket_ts ASC, sensor_type ASC
    """
    with get_engine().connect() as c:
        df = pd.read_sql(
            text(sql),
            c,
            params={"m": machine_id, "s": sensors, "lo": start, "hi": end},
        )
    return df


def fetch_corrective_events() -> pd.DataFrame:
    """Failure events: maintenance_logs entries with maintenance_type='corrective'.

    Returns: machine_id, component_id, failure_ts (UTC midnight of date_performed)
    """
    sql = """
        SELECT machine_id, component_id, date_performed
        FROM maintenance_logs
        WHERE maintenance_type = 'corrective'
        ORDER BY date_performed ASC
    """
    with get_engine().connect() as c:
        df = pd.read_sql(text(sql), c)
    df["failure_ts"] = pd.to_datetime(df["date_performed"], utc=True)
    return df[["machine_id", "component_id", "failure_ts"]]


def fetch_components_meta() -> pd.DataFrame:
    """Return per-(machine, component) metadata for feature use."""
    sql = """
        SELECT c.machine_id, c.component_id, c.expected_lifetime_hours,
               c.hours_since_last_maintenance, c.last_maintenance_date,
               m.installation_date
        FROM components c
        JOIN machines m USING (machine_id)
    """
    with get_engine().connect() as c:
        df = pd.read_sql(text(sql), c)
    df["last_maintenance_date"] = pd.to_datetime(df["last_maintenance_date"], utc=True)
    df["installation_date"] = pd.to_datetime(df["installation_date"], utc=True)
    return df


def fetch_latest_timestamp() -> datetime:
    """Most recent reading in sensor_readings — used as 'as_of' default."""
    with get_engine().connect() as c:
        ts = c.execute(text(
            "SELECT MAX(timestamp) FROM sensor_readings"
        )).scalar()
    return ts
