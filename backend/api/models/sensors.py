from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SensorReading(BaseModel):
    sensor_type: str
    machine_id: str
    component_id: str
    value: float
    unit: str
    timestamp: str  # ISO 8601 UTC
    is_anomaly: bool


class SensorReadingList(BaseModel):
    machine_id: str
    readings: list[SensorReading]
    last_updated: str


class NormalRange(BaseModel):
    min: float
    max: float


class SensorHistoryPoint(BaseModel):
    timestamp: str
    value: float
    min: Optional[float] = None
    max: Optional[float] = None


class SensorHistory(BaseModel):
    machine_id: str
    sensor_type: str
    unit: str
    window: str
    aggregation: str
    normal_range: NormalRange
    points: list[SensorHistoryPoint]
