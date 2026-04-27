from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import RiskTier


class Component(BaseModel):
    component_id: str
    machine_id: str
    name: str
    is_critical: bool
    risk_score: int = Field(ge=0, le=100)
    risk_tier: RiskTier
    expected_lifetime_hours: int
    hours_since_last_maintenance: int
    last_maintenance_date: Optional[str] = None  # ISO date


class ComponentList(BaseModel):
    machine_id: str
    components: list[Component]


class RiskScore(BaseModel):
    machine_id: str
    score: int = Field(ge=0, le=100)
    tier: RiskTier
    highest_risk_component_id: Optional[str] = None
    last_updated: str  # ISO 8601 UTC


class SensorContribution(BaseModel):
    sensor_type: str
    contribution_percent: int


class ComponentRiskScore(BaseModel):
    machine_id: str
    component_id: str
    score: int = Field(ge=0, le=100)
    tier: RiskTier
    predicted_failure_window_hours: Optional[int] = None
    top_contributing_sensors: list[SensorContribution]
    last_updated: str
