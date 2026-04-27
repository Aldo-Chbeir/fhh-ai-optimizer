from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
import asyncpg

from ..db import get_conn
from ..errors import MarketNotFound, SKUNotFound
from ..models import (
    Product, ProductList, Market, MarketList,
    ForecastPoint, SeasonalityEvent, Forecast,
    ScenarioRequest, ScenarioResponse, DeltaSummary,
    DemandAnomaly, DemandAnomalyList,
    Seasonality, SeasonalityMonthIndex, SeasonalityNamedEvent,
)
from ..services.constants import MARKET_NAMES, VALID_MARKET_IDS
from ..services.forecast import (
    apply_scenario, build_forecast, seasonality_for,
)

router = APIRouter(tags=["demand"])


# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------

@router.get("/products", response_model=ProductList)
async def list_products(conn: asyncpg.Connection = Depends(get_conn)) -> ProductList:
    rows = await conn.fetch(
        "SELECT sku, name, category, unit FROM products ORDER BY sku"
    )
    products = [Product(**dict(r)) for r in rows]
    return ProductList(products=products, total=len(products))


@router.get("/markets", response_model=MarketList)
async def list_markets(conn: asyncpg.Connection = Depends(get_conn)) -> MarketList:
    rows = await conn.fetch(
        "SELECT market_id, name, currency FROM markets ORDER BY market_id"
    )
    if rows:
        markets = [Market(**dict(r)) for r in rows]
    else:
        # Fallback: contract-defined static list, in case the DB is empty.
        markets = [
            Market(market_id=mid, name=name, currency=cur)
            for mid, (name, cur) in MARKET_NAMES.items()
        ]
    return MarketList(markets=markets)


# -----------------------------------------------------------------------------
# Forecast
# -----------------------------------------------------------------------------

async def _resolve_sku(conn: asyncpg.Connection, sku: str) -> dict:
    row = await conn.fetchrow(
        "SELECT sku, name, category, unit FROM products WHERE sku = $1", sku
    )
    if not row:
        raise SKUNotFound(sku)
    return dict(row)


@router.get("/forecast", response_model=Forecast)
async def get_forecast(
    sku: str = Query(..., min_length=1),
    market: str = Query(..., min_length=1),
    horizon_months: int = Query(6, ge=1, le=12),
    conn: asyncpg.Connection = Depends(get_conn),
) -> Forecast:
    if market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)
    product = await _resolve_sku(conn, sku)
    f = build_forecast(sku, market, horizon_months, category=product.get("category"))
    return Forecast(
        sku=f["sku"], market=f["market"], horizon_months=f["horizon_months"],
        model=f["model"],
        forecast=[ForecastPoint(**p) for p in f["forecast"]],
        seasonality_events=[SeasonalityEvent(**e) for e in f["seasonality_events"]],
        regressors_used=f["regressors_used"],
        generated_at=f["generated_at"],
    )


@router.post("/forecast/scenario", response_model=ScenarioResponse)
async def post_scenario(
    body: ScenarioRequest = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> ScenarioResponse:
    if body.market not in VALID_MARKET_IDS:
        raise MarketNotFound(body.market)
    product = await _resolve_sku(conn, body.sku)
    base = build_forecast(
        body.sku, body.market, body.horizon_months, category=product.get("category"),
    )
    base_points = base["forecast"]
    scenario_points = apply_scenario(
        base_points,
        body.scenario.type.value,
        body.scenario.magnitude_percent,
        body.scenario.event,
    )

    base_total = sum(p["forecast_value"] for p in base_points)
    scen_total = sum(p["forecast_value"] for p in scenario_points)
    delta_units = scen_total - base_total
    delta_pct = (delta_units / base_total * 100.0) if base_total else 0.0

    return ScenarioResponse(
        baseline_forecast=[ForecastPoint(**p) for p in base_points],
        scenario_forecast=[ForecastPoint(**p) for p in scenario_points],
        delta_summary=DeltaSummary(
            total_baseline_units=float(base_total),
            total_scenario_units=float(scen_total),
            delta_units=float(delta_units),
            delta_percent=round(delta_pct, 1),
        ),
    )


# -----------------------------------------------------------------------------
# Anomalies + seasonality
# -----------------------------------------------------------------------------

# Static demo anomalies; later this becomes a real model output.
_DEMO_ANOMALIES = [
    {
        "anomaly_id": "anm-2026-04-22-003",
        "sku": "fine-baby-s3",
        "market": "ksa",
        "detected_at": "2026-04-22",
        "type": "spike",
        "magnitude_percent": 47.0,
        "explanation": "Sales 47% above expected — possible distributor restocking or demand surge.",
    },
    {
        "anomaly_id": "anm-2026-04-18-007",
        "sku": "fine-toilet-2ply-12",
        "market": "uae",
        "detected_at": "2026-04-18",
        "type": "trend_break",
        "magnitude_percent": 12.0,
        "explanation": "Trend deviates from 90-day baseline; investigate b2b pipeline change.",
    },
]


@router.get("/demand/anomalies", response_model=DemandAnomalyList)
async def get_demand_anomalies() -> DemandAnomalyList:
    return DemandAnomalyList(
        anomalies=[DemandAnomaly(**a) for a in _DEMO_ANOMALIES],
    )


@router.get("/demand/seasonality", response_model=Seasonality)
async def get_seasonality(
    sku: str = Query(..., min_length=1),
    market: Optional[str] = Query(None),
    conn: asyncpg.Connection = Depends(get_conn),
) -> Seasonality:
    if market is not None and market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)
    await _resolve_sku(conn, sku)
    s = seasonality_for(sku, market)
    return Seasonality(
        sku=s["sku"],
        market=s["market"],
        yearly_pattern=[SeasonalityMonthIndex(**m) for m in s["yearly_pattern"]],
        events=[SeasonalityNamedEvent(**e) for e in s["events"]],
    )
