from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .enums import AlarmSeverity, MaintenanceType


class AlertStatus(str, Enum):
    ACTIVE       = "active"
    ACKNOWLEDGED = "acknowledged"
    SCHEDULED    = "scheduled"
    SNOOZED      = "snoozed"
    RESOLVED     = "resolved"


class UnderlyingAlertEvent(BaseModel):
    """One row from a grouped alert — the items the expand toggle on a
    grouped Alert renders inline. Only populated when GET /alerts is
    called with `group_by=component`."""
    alarm_id: str
    alert_id: str
    description: str
    severity: AlarmSeverity
    tier: Literal["healthy", "watch", "warning", "critical"]
    timestamp: Optional[str] = None
    is_informational: bool = False


class Alert(BaseModel):
    alert_id: str
    machine_id: str
    component_id: str
    # `severity` reflects the alarm's original 3-value classification
    # (info / warning / critical) baked into alarm_events at seed time —
    # kept for audit and any external consumer that still reads it.
    # `tier` is the live 4-value bucket derived from the current ML risk
    # score and is what the UI badge displays. The two can disagree
    # (alarm fired as 'info' months ago, model now says 'critical')
    # — `original_severity` is an alias of `severity` named for clarity
    # in tooltips like "Originally fired as: info".
    severity: AlarmSeverity
    tier: Literal["healthy", "watch", "warning", "critical"] = "healthy"
    original_severity: Optional[str] = None
    # True when the description matches a benign-status pattern AND the
    # tier is `healthy`. Frontend hides these by default behind a "Show
    # informational (N hidden)" toggle so the active triage queue shows
    # only signals worth acting on.
    is_informational: bool = False
    risk_score: int = Field(ge=0, le=100)
    title: str
    description: str
    predicted_failure_window_hours: Optional[int] = None
    recommended_action: str
    estimated_cost_if_unaddressed_usd: int
    created_at: str  # ISO 8601 UTC
    acknowledged: bool
    status: AlertStatus = AlertStatus.ACTIVE
    status_changed_at: Optional[str] = None
    status_changed_by: Optional[str] = None
    status_metadata: dict = Field(default_factory=dict)
    # ----- group_by=component additions -----------------------------------
    # All five fields are unset on the per-row default response and
    # populated only when `?group_by=component` aggregates events. None
    # of them break the existing contract — additive only.
    first_triggered_at: Optional[str] = None
    latest_triggered_at: Optional[str] = None
    event_count: Optional[int] = None
    alarm_ids: Optional[list[str]] = None
    underlying_events: Optional[list[UnderlyingAlertEvent]] = None


# ---------------------------------------------------------------------------
# PATCH /alerts/{id}/{action} request + response shapes
# ---------------------------------------------------------------------------

class AcknowledgeBody(BaseModel):
    acknowledged_by: str = Field(min_length=1, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class ScheduleBody(BaseModel):
    scheduled_date: str = Field(min_length=4, max_length=40)  # ISO date or datetime
    technician: str = Field(min_length=1, max_length=120)
    priority: Literal["low", "normal", "high", "emergency"] = "normal"
    notes: Optional[str] = Field(default=None, max_length=2000)


class SnoozeBody(BaseModel):
    snooze_until: str = Field(min_length=4, max_length=40)
    reason: Optional[str] = Field(default=None, max_length=2000)


class ResolveBody(BaseModel):
    resolved_by: str = Field(min_length=1, max_length=120)
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class AlertStatusUpdate(BaseModel):
    """Compact response after a PATCH /alerts/{id}/* call."""
    id: str
    status: AlertStatus
    status_changed_at: Optional[str] = None
    status_metadata: dict = Field(default_factory=dict)


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
    # New per-status counts that mirror the alert tabs in the UI.
    counts_by_status: dict = Field(default_factory=dict)
