"""Tool definitions + execution dispatch for the FHH AI chat assistant.

Each tool maps to a real backend route's underlying service function so
Claude can read live data instead of inventing numbers. We call the
service functions directly (not over HTTP) to keep latency low and avoid
re-entering the FastAPI request stack.

Public surface
--------------
* ``TOOL_SCHEMAS``                — list of Anthropic tool definitions
* ``execute_tool(name, args, conn)`` — async dispatcher

Each tool returns a JSON-serialisable dict that gets serialised into the
``tool_result`` block returned to Claude.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from ..services.alerts import get_alert as _alerts_get_alert
from ..services.constants import (
    COMPONENT_ORDER, VALID_COMPONENT_IDS, VALID_MACHINE_IDS,
    VALID_MARKET_IDS, MARKET_NAMES,
)
from ..services.kpis import overview as _kpi_overview
from ..services.risk import (
    component_risk as _risk_component, machine_risk as _risk_machine,
)
from ..services import demand_prophet, forecast as _forecast_synth

log = logging.getLogger("fhh.api.chat.tools")


# ---------------------------------------------------------------------
# Tool schemas — sent to Anthropic via `tools=` so Claude knows what
# functions are available + their argument shapes.
# ---------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_machines",
        "description": (
            "List all four FHH paper machines with their current overall "
            "risk score, tier, and active alert count. Use when the user "
            "asks 'which machine', 'highest-risk machine', 'fleet status', "
            "or any question that needs to compare machines."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_machine_risk",
        "description": (
            "Read the current risk score (0-100, integer) and tier "
            "(healthy / watch / warning / critical) for a specific "
            "(machine, component) pair, or for a whole machine if "
            "component_id is omitted. Use whenever the user asks for "
            "'the risk on Yankee', 'is Al-Nakheel critical', or any "
            "specific score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_id": {
                    "type": "string",
                    "enum": sorted(VALID_MACHINE_IDS),
                    "description": "One of the four machine IDs.",
                },
                "component_id": {
                    "type": "string",
                    "enum": sorted(VALID_COMPONENT_IDS),
                    "description": "Optional. One of the six component IDs.",
                },
            },
            "required": ["machine_id"],
        },
    },
    {
        "name": "get_machine_detail",
        "description": (
            "Get a comprehensive snapshot of a single machine: identity, "
            "status, OEE, all six components with their risk scores and "
            "maintenance state, and the top failure-window prediction. "
            "Use when the user wants context on a specific machine."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_id": {
                    "type": "string",
                    "enum": sorted(VALID_MACHINE_IDS),
                },
            },
            "required": ["machine_id"],
        },
    },
    {
        "name": "list_alerts",
        "description": (
            "List active (unresolved) alarms with optional filters. "
            "Returns up to `limit` rows plus the total active counts by "
            "severity. Use for 'how many critical alerts', 'what's "
            "broken on Al-Bardi', triage questions, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "Filter by severity (optional).",
                },
                "machine_id": {
                    "type": "string",
                    "enum": sorted(VALID_MACHINE_IDS),
                    "description": "Filter to one machine (optional).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1, "maximum": 25,
                    "description": "Max rows to return (default 5).",
                },
            },
        },
    },
    {
        "name": "get_alert",
        "description": (
            "Get the full detail for one alert (severity, risk_score, "
            "title, description, predicted_failure_window_hours, "
            "recommended_action, estimated_cost_if_unaddressed_usd). Use "
            "when the user asks about a specific alert ID or wants the "
            "deep-dive on the most-critical one returned by list_alerts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string"},
            },
            "required": ["alert_id"],
        },
    },
    {
        "name": "get_forecast",
        "description": (
            "Read the demand forecast for one (market, sku) over the next "
            "`horizon_days` (rounded to whole months internally, max 12 "
            "months). Returns monthly aggregated forecast points with "
            "lower/upper 80%-CI bands, plus seasonality events that fall "
            "in the window. Use for 'what does next month look like' or "
            "any factual demand question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "enum": sorted(VALID_MARKET_IDS),
                },
                "sku": {
                    "type": "string",
                    "description": "Product SKU (e.g. 'fine-facial-100', 'fine-baby-s3').",
                },
                "horizon_days": {
                    "type": "integer",
                    "minimum": 30, "maximum": 365,
                    "description": "Forecast horizon in days (default 90).",
                },
            },
            "required": ["market", "sku"],
        },
    },
    {
        "name": "get_demand_drivers",
        "description": (
            "Get the named demand drivers for one (market, sku): Ramadan, "
            "Eid Al-Fitr, Eid Al-Adha, pre-Ramadan stockup, plus the "
            "12-month yearly seasonality index. Each driver carries an "
            "average lift % derived from the Prophet model. Use for "
            "'what's driving the spike', 'why is March high', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "enum": sorted(VALID_MARKET_IDS),
                },
                "sku": {"type": "string"},
            },
            "required": ["market", "sku"],
        },
    },
    {
        "name": "get_fleet_kpis",
        "description": (
            "Fleet-wide KPIs the user sees on the Overview screen: "
            "fleet_avg_oee_percent, active_critical_alerts, "
            "active_warning_alerts, predicted_downtime_prevented_hours_mtd, "
            "estimated_cost_saved_usd_mtd, machines_running, machines_total."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------

async def _machine_summary(conn: asyncpg.Connection, machine_id: str) -> dict:
    row = await conn.fetchrow(
        """
        SELECT machine_id, name, location, status,
               current_speed_mpm, current_oee_percent
        FROM machines WHERE machine_id = $1
        """,
        machine_id,
    )
    if row is None:
        raise ValueError(f"unknown machine_id '{machine_id}'")
    score, tier, worst = await _risk_machine(conn, machine_id)
    active = await conn.fetchval(
        "SELECT COUNT(*) FROM alarm_events "
        "WHERE machine_id = $1 AND resolved_at IS NULL",
        machine_id,
    ) or 0
    return {
        "machine_id": row["machine_id"],
        "name": row["name"],
        "location": row["location"],
        "status": row["status"],
        "current_speed_mpm": int(row["current_speed_mpm"]),
        "current_oee_percent": float(row["current_oee_percent"]),
        "risk_score": score,
        "risk_tier": tier,
        "highest_risk_component_id": worst,
        "active_alerts_count": int(active),
    }


async def tool_list_machines(conn: asyncpg.Connection, _args: dict) -> dict:
    rows = await conn.fetch("SELECT machine_id FROM machines ORDER BY machine_id")
    machines = [await _machine_summary(conn, r["machine_id"]) for r in rows]
    return {"machines": machines, "total": len(machines)}


async def tool_get_machine_risk(conn: asyncpg.Connection, args: dict) -> dict:
    machine_id = args.get("machine_id")
    component_id = args.get("component_id")
    if not machine_id or machine_id not in VALID_MACHINE_IDS:
        raise ValueError(f"invalid machine_id '{machine_id}'")
    if component_id:
        if component_id not in VALID_COMPONENT_IDS:
            raise ValueError(f"invalid component_id '{component_id}'")
        score, tier, win = await _risk_component(conn, machine_id, component_id)
        return {
            "machine_id": machine_id,
            "component_id": component_id,
            "score": score,
            "tier": tier,
            "predicted_failure_window_hours": win,
        }
    score, tier, worst = await _risk_machine(conn, machine_id)
    return {
        "machine_id": machine_id,
        "score": score,
        "tier": tier,
        "highest_risk_component_id": worst,
    }


async def tool_get_machine_detail(conn: asyncpg.Connection, args: dict) -> dict:
    machine_id = args.get("machine_id")
    if not machine_id or machine_id not in VALID_MACHINE_IDS:
        raise ValueError(f"invalid machine_id '{machine_id}'")
    summary = await _machine_summary(conn, machine_id)

    # Components with risk
    rows = await conn.fetch(
        """
        SELECT component_id, name, is_critical, expected_lifetime_hours,
               hours_since_last_maintenance, last_maintenance_date
        FROM components WHERE machine_id = $1
        """,
        machine_id,
    )
    by_id = {r["component_id"]: r for r in rows}
    components = []
    for cid in COMPONENT_ORDER:
        r = by_id.get(cid)
        if not r:
            continue
        score, tier, win = await _risk_component(conn, machine_id, cid)
        components.append({
            "component_id": r["component_id"],
            "name": r["name"],
            "is_critical": bool(r["is_critical"]),
            "risk_score": score,
            "risk_tier": tier,
            "predicted_failure_window_hours": win,
            "hours_since_last_maintenance": int(r["hours_since_last_maintenance"]),
            "last_maintenance_date": (
                r["last_maintenance_date"].isoformat()
                if r["last_maintenance_date"] else None
            ),
        })
    return {**summary, "components": components}


async def tool_list_alerts(conn: asyncpg.Connection, args: dict) -> dict:
    """Lightweight alert list — reads alarm_events directly without per-row
    ML inference. The richer risk_score/title shape lives in `get_alert`."""
    severity = args.get("severity")
    machine_id = args.get("machine_id")
    limit = max(1, min(int(args.get("limit", 5)), 25))

    sql = (
        "SELECT alarm_id, machine_id, timestamp, severity, description "
        "FROM alarm_events WHERE resolved_at IS NULL"
    )
    params: list = []
    if severity:
        params.append(severity)
        sql += f" AND severity = ${len(params)}"
    if machine_id:
        params.append(machine_id)
        sql += f" AND machine_id = ${len(params)}"
    sql += " ORDER BY "
    # Critical first, then most-recent.
    sql += (
        "CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
        "timestamp DESC"
    )
    params.append(limit)
    sql += f" LIMIT ${len(params)}"

    rows = await conn.fetch(sql, *params)
    alerts = [
        {
            "alarm_id": r["alarm_id"],
            "alert_id": "alt-" + r["alarm_id"][4:] if r["alarm_id"].startswith("alm-") else r["alarm_id"],
            "machine_id": r["machine_id"],
            "severity": r["severity"],
            "description": r["description"],
            "timestamp": r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for r in rows
    ]

    crit = await conn.fetchval(
        "SELECT COUNT(*) FROM alarm_events "
        "WHERE severity = 'critical' AND resolved_at IS NULL"
    ) or 0
    warn = await conn.fetchval(
        "SELECT COUNT(*) FROM alarm_events "
        "WHERE severity = 'warning' AND resolved_at IS NULL"
    ) or 0
    info = await conn.fetchval(
        "SELECT COUNT(*) FROM alarm_events "
        "WHERE severity = 'info' AND resolved_at IS NULL"
    ) or 0

    return {
        "alerts": alerts,
        "filtered_results_returned": len(alerts),
        "total_active_critical": int(crit),
        "total_active_warning": int(warn),
        "total_active_info": int(info),
    }


async def tool_get_alert(conn: asyncpg.Connection, args: dict) -> dict:
    alert_id = args.get("alert_id")
    if not alert_id:
        raise ValueError("alert_id is required")
    a = await _alerts_get_alert(conn, alert_id)
    if a is None:
        raise ValueError(f"alert '{alert_id}' not found")
    return a


async def tool_get_forecast(conn: asyncpg.Connection, args: dict) -> dict:
    market = args.get("market")
    sku = args.get("sku")
    horizon_days = int(args.get("horizon_days", 90))
    if market not in VALID_MARKET_IDS:
        raise ValueError(f"invalid market '{market}'")

    # Validate SKU
    row = await conn.fetchrow("SELECT sku, name, category FROM products WHERE sku = $1", sku)
    if not row:
        raise ValueError(f"unknown sku '{sku}'")

    horizon_months = max(1, min(round(horizon_days / 30) or 1, 12))

    if demand_prophet.model_exists(market, sku):
        payload = await demand_prophet.forecast_contract_shape(
            market_id=market, product_id=sku, horizon_months=horizon_months,
        )
        # Strip internal extras that aren't useful for the model.
        public = {k: v for k, v in payload.items() if not k.startswith("_")}
        return public

    # Fallback: synthetic forecast (works on a fresh checkout pre-training).
    return _forecast_synth.build_forecast(
        sku, market, horizon_months, category=row["category"],
    )


async def tool_get_demand_drivers(conn: asyncpg.Connection, args: dict) -> dict:
    market = args.get("market")
    sku = args.get("sku")
    if market not in VALID_MARKET_IDS:
        raise ValueError(f"invalid market '{market}'")
    row = await conn.fetchrow("SELECT sku FROM products WHERE sku = $1", sku)
    if not row:
        raise ValueError(f"unknown sku '{sku}'")

    if demand_prophet.model_exists(market, sku):
        decomp = await demand_prophet.decomposition_for(market, sku)
        events = decomp.get("regressors", {}) or {}
        # Aggregate Ramadan / Eid lifts from per-day numbers
        named: dict[str, list[float]] = {}
        for key in (
            "is_ramadan", "is_eid_alfitr", "is_eid_aladha",
            "is_pre_ramadan_stockup", "promo_active",
        ):
            for entry in events.get(key, []) or []:
                named.setdefault(key, []).append(float(entry["lift_pct"]))
        avg = {k: round(sum(v) / len(v), 1) for k, v in named.items() if v}
        return {
            "market": market, "sku": sku,
            "named_drivers_avg_lift_pct": avg,
            "yearly_pattern": decomp.get("yearly", []),
            "weekly_pattern": decomp.get("weekly", []),
        }

    # Fallback: synthetic
    s = _forecast_synth.seasonality_for(sku, market)
    return {
        "market": market, "sku": sku,
        "named_drivers_avg_lift_pct": {
            e["name"]: e["average_lift_percent"] for e in s["events"]
        },
        "yearly_pattern": [{"month": p["month"], "index": p["index"]} for p in s["yearly_pattern"]],
        "weekly_pattern": [],
    }


async def tool_get_fleet_kpis(conn: asyncpg.Connection, _args: dict) -> dict:
    return await _kpi_overview(conn)


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------

_DISPATCH = {
    "list_machines":      tool_list_machines,
    "get_machine_risk":   tool_get_machine_risk,
    "get_machine_detail": tool_get_machine_detail,
    "list_alerts":        tool_list_alerts,
    "get_alert":          tool_get_alert,
    "get_forecast":       tool_get_forecast,
    "get_demand_drivers": tool_get_demand_drivers,
    "get_fleet_kpis":     tool_get_fleet_kpis,
}


async def execute_tool(name: str, args: dict, conn: asyncpg.Connection) -> dict:
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"unknown tool '{name}'")
    return await fn(conn, args or {})
