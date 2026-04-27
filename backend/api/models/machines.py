from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import MachineStatus, RiskTier


class Machine(BaseModel):
    machine_id: str
    name: str
    location: str
    model: str
    installation_date: str  # ISO date YYYY-MM-DD
    status: MachineStatus
    current_speed_mpm: int
    current_oee_percent: float
    risk_score: int = Field(ge=0, le=100)
    risk_tier: RiskTier
    active_alerts_count: int


class MachineList(BaseModel):
    machines: list[Machine]
    total: int
