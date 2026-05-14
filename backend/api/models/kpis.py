from __future__ import annotations

from pydantic import BaseModel


class KPIOverview(BaseModel):
    fleet_avg_oee_percent: float
    # `active_critical_alerts` / `active_warning_alerts` are now counts of
    # MACHINES whose worst component is in the corresponding ML tier
    # (critical ≥70, warning 50-69), not alarm-row counts. Field name kept
    # for API back-compat with the frontend KPI tiles.
    active_critical_alerts: int
    active_warning_alerts: int
    predicted_downtime_prevented_hours_mtd: float
    estimated_cost_saved_usd_mtd: float
    machines_running: int
    machines_total: int
    last_updated: str


class MachineCostBreakdown(BaseModel):
    machine_id: str
    cost_saved_usd: float


class CostSavings(BaseModel):
    window: str
    total_predictions: int
    predictions_acted_on: int
    estimated_downtime_hours_prevented: float
    estimated_cost_saved_usd: float
    breakdown_by_machine: list[MachineCostBreakdown]
