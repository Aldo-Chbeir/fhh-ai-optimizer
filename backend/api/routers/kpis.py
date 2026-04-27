from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import asyncpg

from ..db import get_conn
from ..models import (
    KPIOverview, CostSavings, MachineCostBreakdown, CostSavingsWindow,
)
from ..services.kpis import overview, cost_savings

router = APIRouter(prefix="/kpis", tags=["kpis"])


@router.get("/overview", response_model=KPIOverview)
async def kpi_overview(conn: asyncpg.Connection = Depends(get_conn)) -> KPIOverview:
    data = await overview(conn)
    return KPIOverview(**data)


@router.get("/cost-savings", response_model=CostSavings)
async def kpi_cost_savings(
    window: CostSavingsWindow = Query(CostSavingsWindow.YTD),
    conn: asyncpg.Connection = Depends(get_conn),
) -> CostSavings:
    data = await cost_savings(conn, window.value)
    return CostSavings(
        window=data["window"],
        total_predictions=data["total_predictions"],
        predictions_acted_on=data["predictions_acted_on"],
        estimated_downtime_hours_prevented=data["estimated_downtime_hours_prevented"],
        estimated_cost_saved_usd=data["estimated_cost_saved_usd"],
        breakdown_by_machine=[MachineCostBreakdown(**b) for b in data["breakdown_by_machine"]],
    )
