from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import AlarmSeverity, MaintenanceType


class Alert(BaseModel):
    alert_id: str
    machine_id: str
    component_id: str
    severity: AlarmSeverity
    risk_score: int = Field(ge=0, le=100)
    title: str
    description: str
    predicted_failure_window_hours: Optional[int] = None
    recommended_action: str
    estimated_cost_if_unaddressed_usd: int
    created_at: str  # ISO 8601 UTC
    acknowledged: bool


class AlertCounts(BaseModel):
    critical: int = 0
    warning: int = 0
    watch: int = 0
    healthy: int = 0


class AlertList(BaseModel):
    alerts: list[Alert]
    total: int
    counts_by_tier: dict[str, int]


class Alarm(BaseModel):
    alarm_id: str
    timestamp: str
    severity: AlarmSeverity
    description: str
    resolved_at: Optional[str] = None
    downtime_minutes: int


class AlarmList(BaseModel):
    machine_id: str
    alarms: list[Alarm]
    total: int


class MaintenanceLogEntry(BaseModel):
    log_id: str
    component_id: str
    maintenance_type: MaintenanceType
    date_performed: str  # ISO date
    cost_usd: float
    downtime_hours: float
    technician: Optional[str] = None
    notes: Optional[str] = None


class MaintenanceLogList(BaseModel):
    machine_id: str
    logs: list[MaintenanceLogEntry]


class AlertsKPIs(BaseModel):
    """UI extension for the Alerts triage screen — aggregate counters +
    sparklines that the screen renders above the alert list. Not part of
    API_CONTRACT.md v1.1 (intentional UI helper)."""

    active_critical: int
    critical_sparkline_7d: list[int]
    active_warning: int
    warning_sparkline_7d: list[int]
    avg_response_time_minutes: int
    avg_response_time_delta_minutes: int  # negative = faster than last week
    acknowledged_today: int
    acknowledged_today_total: int
    last_updated: str
