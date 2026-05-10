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
    AccuracyReport, AccuracyDailyPoint, ConfidenceCoverage,
)
from ..services.constants import MARKET_NAMES, VALID_MARKET_IDS
from ..services.forecast import (
    apply_scenario, build_forecast, seasonality_for,
)
from ..services import demand_prophet
from ..services.demand_accuracy import accuracy_report

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
        markets = [
            Market(market_id=mid, name=name, currency=cur)
            for mid, (name, cur) in MARKET_NAMES.items()
        ]
    return MarketList(markets=markets)


# -----------------------------------------------------------------------------
# Forecast — Prophet when available, synthetic fallback
# -----------------------------------------------------------------------------

async def _resolve_sku(conn: asyncpg.Connection, sku: str) -> dict:
    row = await conn.fetchrow(
        "SELECT sku, name, category, unit FROM products WHERE sku = $1", sku
    )
    if not row:
        raise SKUNotFound(sku)
    return dict(row)


def _drop_extras(payload: dict) -> dict:
    """Strip the `_extras` block that's helpful internally but not in the contract."""
    return {k: v for k, v in payload.items() if not k.startswith("_")}


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

    if demand_prophet.model_exists(market, sku):
        payload = await demand_prophet.forecast_contract_shape(
            market_id=market, product_id=sku, horizon_months=horizon_months,
        )
        payload = _drop_extras(payload)
    else:
        payload = build_forecast(
            sku, market, horizon_months, category=product.get("category"),
        )

    return Forecast(
        sku=payload["sku"], market=payload["market"],
        horizon_months=payload["horizon_months"], model=payload["model"],
        forecast=[ForecastPoint(**p) for p in payload["forecast"]],
        seasonality_events=[SeasonalityEvent(**e) for e in payload["seasonality_events"]],
        regressors_used=payload["regressors_used"],
        generated_at=payload["generated_at"],
    )


# -----------------------------------------------------------------------------
# Scenario — Prophet path translates contract scenario types into regressor overrides
# -----------------------------------------------------------------------------

def _contract_scenario_to_overrides(scenario_type: str, magnitude_pct: float,
                                    event: Optional[str]) -> dict:
    """Map the contract's scenario block into Prophet regressor overrides.

    Contract types: seasonality_shift · price_change · competitor_entry · supply_disruption
    """
    overrides: dict = {}
    if scenario_type == "seasonality_shift":
        if (event or "").lower() == "ramadan":
            # +30% magnitude → multiplier 1.3
            overrides["ramadan_intensity_multiplier"] = 1.0 + magnitude_pct / 100.0
    elif scenario_type == "price_change":
        # Rough demand elasticity ≈ -1.2 → +30% price → -36% demand → mass-promo "negative"
        # We model this as a fractional promo-active flag with an inverted sign:
        # negative price_change → cheaper → more promo days.
        if magnitude_pct < 0:
            overrides["promo_boost"] = min(0.5, abs(magnitude_pct) / 100.0)
    elif scenario_type == "competitor_entry":
        # Lower demand: simulate by zeroing Ramadan boost and damping promos
        overrides["disable_ramadan"] = True
    elif scenario_type == "supply_disruption":
        overrides["disable_ramadan"] = True
        overrides["promo_boost"] = 0.0
    return overrides


@router.post("/forecast/scenario", response_model=ScenarioResponse)
async def post_scenario(
    body: ScenarioRequest = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> ScenarioResponse:
    if body.market not in VALID_MARKET_IDS:
        raise MarketNotFound(body.market)
    product = await _resolve_sku(conn, body.sku)

    if demand_prophet.model_exists(body.market, body.sku):
        baseline_payload = _drop_extras(
            await demand_prophet.forecast_contract_shape(
                market_id=body.market, product_id=body.sku,
                horizon_months=body.horizon_months,
            )
        )
        overrides = _contract_scenario_to_overrides(
            body.scenario.type.value,
            body.scenario.magnitude_percent,
            body.scenario.event,
        )
        scenario_payload = _drop_extras(
            await demand_prophet.forecast_contract_shape(
                market_id=body.market, product_id=body.sku,
                horizon_months=body.horizon_months,
                scenario_overrides=overrides,
            )
        )
        base_points = baseline_payload["forecast"]
        scen_points = scenario_payload["forecast"]
    else:
        base = build_forecast(body.sku, body.market, body.horizon_months,
                              category=product.get("category"))
        base_points = base["forecast"]
        scen_points = apply_scenario(
            base_points,
            body.scenario.type.value,
            body.scenario.magnitude_percent,
            body.scenario.event,
        )

    base_total = sum(p["forecast_value"] for p in base_points)
    scen_total = sum(p["forecast_value"] for p in scen_points)
    delta_units = scen_total - base_total
    delta_pct = (delta_units / base_total * 100.0) if base_total else 0.0

    return ScenarioResponse(
        baseline_forecast=[ForecastPoint(**p) for p in base_points],
        scenario_forecast=[ForecastPoint(**p) for p in scen_points],
        delta_summary=DeltaSummary(
            total_baseline_units=float(base_total),
            total_scenario_units=float(scen_total),
            delta_units=float(delta_units),
            delta_percent=round(delta_pct, 1),
        ),
    )


# -----------------------------------------------------------------------------
# Anomalies — backed by real `demand_history` (Prophet residuals)
# -----------------------------------------------------------------------------

@router.get("/demand/anomalies", response_model=DemandAnomalyList)
async def get_demand_anomalies(
    market: Optional[str] = Query(None),
    sku: Optional[str] = Query(None),
    days: int = Query(60, ge=7, le=365),
    conn: asyncpg.Connection = Depends(get_conn),
) -> DemandAnomalyList:
    """Return recent dates where actual `units_sold` deviates from the
    7-day rolling baseline by more than 25 %. Used by Screen 4 of the UI.
    """
    if market is not None and market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)

    sql = """
    WITH bounds AS (SELECT MAX(date) AS hi FROM demand_history),
    win AS (
        SELECT d.date, d.market_id, d.product_id, d.units_sold,
               AVG(d.units_sold) OVER (
                 PARTITION BY d.market_id, d.product_id
                 ORDER BY d.date
                 ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
               ) AS baseline
        FROM demand_history d, bounds
        WHERE d.date > (bounds.hi - $1::int * INTERVAL '1 day')
    )
    SELECT date, market_id, product_id, units_sold, baseline,
           CASE WHEN baseline > 0
                THEN 100.0 * (units_sold - baseline) / baseline
                ELSE 0
           END AS pct_dev
    FROM win
    WHERE baseline IS NOT NULL
      AND baseline > 0
      AND ABS(100.0 * (units_sold - baseline) / baseline) >= 25
    """
    params: list = [days]
    if market is not None:
        params.append(market)
        sql += f" AND market_id = ${len(params)}"
    if sku is not None:
        params.append(sku)
        sql += f" AND product_id = ${len(params)}"
    sql += " ORDER BY ABS(100.0 * (units_sold - baseline) / baseline) DESC LIMIT 10"

    rows = await conn.fetch(sql, *params)

    anomalies: list[DemandAnomaly] = []
    for r in rows:
        pct = float(r["pct_dev"])
        kind = "spike" if pct > 0 else "dip"
        anomalies.append(DemandAnomaly(
            anomaly_id=f"anm-{r['date'].isoformat()}-{r['market_id']}-{r['product_id'][:18]}",
            sku=r["product_id"],
            market=r["market_id"],
            detected_at=r["date"].isoformat(),
            type=kind,
            magnitude_percent=round(abs(pct), 1),
            explanation=f"Units {kind} {abs(pct):.0f}% vs the prior 14-day baseline.",
        ))

    return DemandAnomalyList(anomalies=anomalies)


# -----------------------------------------------------------------------------
# Accuracy report — coverage + per-day forecast vs actual for one (market, sku)
# -----------------------------------------------------------------------------

@router.get("/demand/accuracy", response_model=AccuracyReport)
async def get_demand_accuracy(
    market: str = Query(..., min_length=1),
    sku: str = Query(..., min_length=1),
    days: int = Query(90, ge=7, le=365),
    conn: asyncpg.Connection = Depends(get_conn),
) -> AccuracyReport:
    if market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)
    product = await _resolve_sku(conn, sku)

    payload = accuracy_report(
        sku=sku, market=market, days=days, category=product.get("category"),
    )
    return AccuracyReport(
        market=payload["market"], sku=payload["sku"],
        period_days=payload["period_days"], mape=payload["mape"],
        confidence_coverage=ConfidenceCoverage(**payload["confidence_coverage"]),
        daily=[AccuracyDailyPoint(**d) for d in payload["daily"]],
        model=payload["model"], generated_at=payload["generated_at"],
    )


# -----------------------------------------------------------------------------
# Seasonality — Prophet decomposition when available, synthetic fallback
# -----------------------------------------------------------------------------

@router.get("/demand/seasonality", response_model=Seasonality)
async def get_seasonality(
    sku: str = Query(..., min_length=1),
    market: Optional[str] = Query(None),
    conn: asyncpg.Connection = Depends(get_conn),
) -> Seasonality:
    if market is not None and market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)
    await _resolve_sku(conn, sku)

    # If Prophet is available + the market is specified, compute the per-market
    # decomposition from the model. Otherwise return the synthetic seasonality.
    if market and demand_prophet.model_exists(market, sku):
        # Convert Prophet's `yearly` daily curve into the 12-month index
        # the contract expects (1.0 = average).
        decomp = await demand_prophet.decomposition_for(market, sku)
        yearly_pattern = _yearly_to_monthly(decomp.get("yearly", []))
        events = _seasonality_events_from_decomp(decomp.get("regressors", {}))
        return Seasonality(
            sku=sku, market=market,
            yearly_pattern=[SeasonalityMonthIndex(**m) for m in yearly_pattern],
            events=[SeasonalityNamedEvent(**e) for e in events],
        )

    s = seasonality_for(sku, market)
    return Seasonality(
        sku=s["sku"], market=s["market"],
        yearly_pattern=[SeasonalityMonthIndex(**m) for m in s["yearly_pattern"]],
        events=[SeasonalityNamedEvent(**e) for e in s["events"]],
    )


def _yearly_to_monthly(yearly: list[dict]) -> list[dict]:
    """Aggregate Prophet's day-of-year curve into a 12-month index where
    1.0 = annual average. Yearly values come back as multiplicative deltas
    (e.g. 0.18 = +18 %), so we convert to absolute and renormalise."""
    if not yearly:
        return [{"month": i, "index": 1.0} for i in range(1, 13)]
    import math
    monthly_sums: dict[int, list[float]] = {i: [] for i in range(1, 13)}
    for row in yearly:
        doy = int(row["day_of_year"])
        # Approx: doy 1-31 → Jan, 32-59 → Feb, etc.
        cumdays = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 366]
        m = next(i for i in range(1, 13) if doy <= cumdays[i])
        monthly_sums[m].append(float(row["value"]))
    avg_per_month = {m: (sum(v) / len(v) if v else 0.0) for m, v in monthly_sums.items()}
    overall = sum(avg_per_month.values()) / 12.0
    out = []
    for m in range(1, 13):
        index = 1.0 + (avg_per_month[m] - overall)
        out.append({"month": m, "index": round(float(index), 3)})
    return out


def _seasonality_events_from_decomp(regressors: dict) -> list[dict]:
    """Surface Ramadan / Eid as named events with average lift %."""
    out: list[dict] = []
    name_map = {
        "is_ramadan": "ramadan",
        "is_eid_alfitr": "eid_al_fitr",
        "is_eid_aladha": "eid_al_adha",
        "is_pre_ramadan_stockup": "pre_ramadan_stockup",
    }
    for key, friendly in name_map.items():
        lifts = regressors.get(key) or []
        if not lifts:
            continue
        avg = sum(item["lift_pct"] for item in lifts) / len(lifts)
        out.append({"name": friendly, "average_lift_percent": round(float(avg), 2)})
    return out
