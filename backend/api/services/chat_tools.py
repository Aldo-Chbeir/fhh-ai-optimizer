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
    COMPONENT_ORDER, COMPONENT_SENSORS, SENSOR_META,
    VALID_COMPONENT_IDS, VALID_MACHINE_IDS,
    VALID_MARKET_IDS, MARKET_NAMES,
)
from ..services.kpis import overview as _kpi_overview
from ..services.risk import (
    component_risk as _risk_component, machine_risk as _risk_machine,
)
from ..services import demand_prophet, forecast as _forecast_synth

log = logging.getLogger("fhh.api.chat.tools")


# ---------------------------------------------------------------------
# Threshold table — used by `get_sensor_readings` (`breached` flag) and
# `get_component_root_cause`. Critical = "out of spec, alert worthy",
# warning = "approaching out of spec". Values picked to match the seeded
# sensor data (so the bearing-1 6.93 mm/s historical readings on
# Al-Nakheel correctly flag as breached).
#
# `unit` is the same string surfaced by the contract sensor metadata.
# Direction: most sensors here flag `value >= critical` as a breach
# (high-side). qcs_softness_index is low-bad (low quality) and we leave
# it unflagged here; a future iteration can model two-sided thresholds.
# ---------------------------------------------------------------------
SENSOR_THRESHOLDS: dict[str, dict[str, float]] = {
    "yankee_surface_temp":         {"critical": 125.0, "warning": 122.0},
    "yankee_steam_pressure":       {"critical": 11.0,  "warning": 10.5},
    "yankee_vibration_bearing_1":  {"critical": 6.0,   "warning": 4.5},
    "yankee_vibration_bearing_2":  {"critical": 6.0,   "warning": 4.5},
    "yankee_vibration_bearing_3":  {"critical": 6.0,   "warning": 4.5},
    "yankee_blade_pressure":       {"critical": 130.0, "warning": 125.0},
    "visconip_nip_pressure":       {"critical": 7.0,   "warning": 6.5},
    "visconip_felt_moisture":      {"critical": 50.0,  "warning": 47.0},
    "aircap_inlet_temp":           {"critical": 540.0, "warning": 525.0},
    "aircap_energy":               {"critical": 2.8,   "warning": 2.5},
    "headbox_stock_temp":          {"critical": 60.0,  "warning": 57.0},
    "softreel_tension":            {"critical": 240.0, "warning": 225.0},
    "rewinder_speed":              {"critical": 2300.0,"warning": 2250.0},
}


def _threshold_for(sensor_type: str) -> dict:
    """Return {critical, warning, unit} for a sensor_type. Unit comes from
    the contract sensor metadata so callers don't have to hard-code units
    twice."""
    t = SENSOR_THRESHOLDS.get(sensor_type, {})
    meta = SENSOR_META.get(sensor_type)  # (component_id, unit, normal_min, normal_max)
    unit = meta[1] if meta else ""
    return {
        "critical": t.get("critical"),
        "warning": t.get("warning"),
        "unit": unit,
    }


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
            "List alerts with optional filters. Defaults to non-resolved "
            "rows (active / acknowledged / scheduled / snoozed); pass "
            "status='resolved' to see closed alerts. Each row carries the "
            "triage status so you can answer 'how many alerts has the "
            "operator acknowledged today', 'what's still active', etc. "
            "Returns up to `limit` rows plus per-status totals across "
            "the whole table."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "Filter by severity (optional).",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "acknowledged", "scheduled",
                             "snoozed", "resolved"],
                    "description": "Filter by triage status (optional).",
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
    {
        "name": "get_sensor_readings",
        "description": (
            "Read raw sensor readings for a specific (machine, component) "
            "pair. Use this to back up a prediction with actual numbers — "
            "e.g. when the user asks 'show me the data', 'what readings "
            "drove that score', or 'give me the recent vibration values'. "
            "`order='highest'` surfaces the most extreme historical "
            "readings (365-day window); `order='recent'` returns the "
            "latest values (30-day window). Each reading carries a "
            "`breached` flag against the sensor's critical threshold."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_id": {
                    "type": "string",
                    "enum": sorted(VALID_MACHINE_IDS),
                },
                "component_id": {
                    "type": "string",
                    "enum": sorted(VALID_COMPONENT_IDS),
                },
                "sensor_type": {
                    "type": "string",
                    "enum": sorted(SENSOR_THRESHOLDS.keys()),
                    "description": (
                        "Which sensor to read. Optional — if omitted, "
                        "auto-picks the sensor with the highest "
                        "365-day max value vs its critical threshold "
                        "(i.e. the most likely root-cause sensor)."
                    ),
                },
                "min_value": {
                    "type": "number",
                    "description": "Filter to readings >= this value.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1, "maximum": 200,
                    "description": "Max rows (default 20).",
                },
                "order": {
                    "type": "string",
                    "enum": ["recent", "highest"],
                    "description": (
                        "'recent' → newest readings, 30-day window. "
                        "'highest' → largest values, 365-day window."
                    ),
                },
            },
            "required": ["machine_id", "component_id"],
        },
    },
    {
        "name": "get_component_root_cause",
        "description": (
            "Identify which sensor is most responsible for a component's "
            "current risk. Walks every sensor on the component, scores "
            "each by its max-365-day value vs its critical threshold, "
            "and returns the top driver plus up to three contributing "
            "drivers. Use this BEFORE get_sensor_readings when the user "
            "asks 'why is X critical', 'what's the root cause', 'what "
            "sensor drove this'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_id": {
                    "type": "string",
                    "enum": sorted(VALID_MACHINE_IDS),
                },
                "component_id": {
                    "type": "string",
                    "enum": sorted(VALID_COMPONENT_IDS),
                },
            },
            "required": ["machine_id", "component_id"],
        },
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
    status = args.get("status")
    limit = max(1, min(int(args.get("limit", 5)), 25))

    valid_statuses = {"active", "acknowledged", "scheduled", "snoozed", "resolved"}
    if status and status not in valid_statuses:
        raise ValueError(f"invalid status '{status}'")

    sql = (
        "SELECT alarm_id, machine_id, timestamp, severity, description, "
        "status, status_changed_at, status_changed_by "
        "FROM alarm_events WHERE 1=1"
    )
    params: list = []
    if status:
        params.append(status)
        sql += f" AND status = ${len(params)}"
    else:
        # Default: hide resolved rows so chat answers focus on actionable items.
        sql += " AND status <> 'resolved'"
    if severity:
        params.append(severity)
        sql += f" AND severity = ${len(params)}"
    if machine_id:
        params.append(machine_id)
        sql += f" AND machine_id = ${len(params)}"
    sql += (
        " ORDER BY "
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
            "status": r["status"] or "active",
            "status_changed_by": r["status_changed_by"],
            "status_changed_at": (
                r["status_changed_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if r["status_changed_at"] else None
            ),
            "description": r["description"],
            "timestamp": r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for r in rows
    ]

    # Per-(severity, status) totals so the chat can answer "how many active
    # criticals" or "how many alerts have I acknowledged today" without a
    # follow-up query.
    matrix_rows = await conn.fetch(
        "SELECT severity, status, COUNT(*) AS n FROM alarm_events "
        "GROUP BY severity, status"
    )
    counts_by_severity: dict[str, dict[str, int]] = {}
    for r in matrix_rows:
        counts_by_severity.setdefault(r["severity"], {})[r["status"]] = int(r["n"])

    counts_by_status_total: dict[str, int] = {}
    for r in matrix_rows:
        counts_by_status_total[r["status"]] = (
            counts_by_status_total.get(r["status"], 0) + int(r["n"])
        )
    for s in ("active", "acknowledged", "scheduled", "snoozed", "resolved"):
        counts_by_status_total.setdefault(s, 0)

    # Acknowledged-today (any severity, status changed to ack/sch/snz today)
    ack_today = await conn.fetchval(
        """
        SELECT COUNT(*) FROM alarm_events
        WHERE status IN ('acknowledged','scheduled','snoozed')
          AND status_changed_at::date = (
            SELECT MAX(timestamp)::date FROM alarm_events
          )
        """
    ) or 0

    return {
        "alerts": alerts,
        "filtered_results_returned": len(alerts),
        "counts_by_status": counts_by_status_total,
        "counts_by_severity_status": counts_by_severity,
        "acknowledged_today": int(ack_today),
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
# Explainability tools — back up predictions with the actual sensor data
# the model leaned on. Used when the user asks "why" / "show me the
# data" / "give me the readings".
# ---------------------------------------------------------------------

def _component_sensors_for(component_id: str) -> list[str]:
    """All sensors attributed to a component. Returns [] for unknown ids."""
    return list(COMPONENT_SENSORS.get(component_id, []))


async def _latest_value(
    conn: asyncpg.Connection, machine_id: str, sensor_type: str,
) -> tuple[Optional[float], Optional[datetime]]:
    row = await conn.fetchrow(
        """
        SELECT value, timestamp FROM sensor_readings
        WHERE machine_id = $1 AND sensor_type = $2
        ORDER BY timestamp DESC LIMIT 1
        """,
        machine_id, sensor_type,
    )
    if row is None:
        return None, None
    return float(row["value"]), row["timestamp"]


async def _max_value_in_window(
    conn: asyncpg.Connection, machine_id: str, sensor_type: str, window_days: int = 365,
) -> tuple[Optional[float], Optional[datetime]]:
    row = await conn.fetchrow(
        f"""
        SELECT value, timestamp FROM sensor_readings
        WHERE machine_id = $1 AND sensor_type = $2
          AND timestamp > (SELECT MAX(timestamp) FROM sensor_readings)
                          - INTERVAL '{int(window_days)} days'
        ORDER BY value DESC LIMIT 1
        """,
        machine_id, sensor_type,
    )
    if row is None:
        return None, None
    return float(row["value"]), row["timestamp"]


async def _pick_worst_breaching_sensor(
    conn: asyncpg.Connection, machine_id: str, component_id: str,
) -> Optional[str]:
    """Auto-pick the sensor whose 365-day max value is most over its
    critical threshold. Returns None if no sensor on this component has
    a defined threshold."""
    sensors = _component_sensors_for(component_id)
    best: tuple[float, str] | None = None
    for s in sensors:
        crit = SENSOR_THRESHOLDS.get(s, {}).get("critical")
        if crit is None:
            continue
        max_v, _ = await _max_value_in_window(conn, machine_id, s, window_days=365)
        if max_v is None:
            continue
        # Pick the sensor with the largest exceedance ratio (max_v / critical).
        # Even sensors below their threshold get scored here so the tool
        # always returns something, with negative headroom indicating safe.
        score = max_v / crit
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else (sensors[0] if sensors else None)


async def tool_get_sensor_readings(conn: asyncpg.Connection, args: dict) -> dict:
    machine_id = args.get("machine_id")
    component_id = args.get("component_id")
    sensor_type = args.get("sensor_type")
    min_value = args.get("min_value")
    limit = max(1, min(int(args.get("limit", 20)), 200))
    order = args.get("order") or "recent"
    if order not in ("recent", "highest"):
        raise ValueError(f"invalid order '{order}'; expected 'recent' or 'highest'")

    if not machine_id or machine_id not in VALID_MACHINE_IDS:
        raise ValueError(f"invalid machine_id '{machine_id}'")
    if not component_id or component_id not in VALID_COMPONENT_IDS:
        raise ValueError(f"invalid component_id '{component_id}'")

    # Auto-pick worst-breaching sensor when caller didn't specify one.
    if not sensor_type:
        sensor_type = await _pick_worst_breaching_sensor(conn, machine_id, component_id)
        if not sensor_type:
            raise ValueError(
                f"no sensor metadata available for component '{component_id}'"
            )

    # Validate the sensor belongs to this component (or is qcs, the
    # cross-component quality signal).
    component_sensors = _component_sensors_for(component_id)
    if sensor_type not in component_sensors and sensor_type != "qcs_softness_index":
        raise ValueError(
            f"sensor '{sensor_type}' is not on component '{component_id}'"
        )

    th = _threshold_for(sensor_type)
    crit = th.get("critical")
    warn = th.get("warning")
    unit = th.get("unit") or ""

    # `recent` order pulls a tight 30-day window so chat answers about
    # "the last week" don't stretch into prior maintenance cycles.
    # `highest` order widens to 365 days so historical breaches surface
    # — the user's example case ("bearing 1 hit 6.93 mm/s") references
    # readings from 7 months ago.
    window_days = 30 if order == "recent" else 365

    sql = (
        "SELECT timestamp, value FROM sensor_readings "
        "WHERE machine_id = $1 AND sensor_type = $2 "
        f"  AND timestamp > (SELECT MAX(timestamp) FROM sensor_readings) "
        f"                  - INTERVAL '{window_days} days'"
    )
    params: list = [machine_id, sensor_type]
    if min_value is not None:
        params.append(float(min_value))
        sql += f" AND value >= ${len(params)}"
    if order == "highest":
        sql += " ORDER BY value DESC, timestamp DESC"
    else:
        sql += " ORDER BY timestamp DESC"
    params.append(limit)
    sql += f" LIMIT ${len(params)}"

    rows = await conn.fetch(sql, *params)
    readings = []
    for r in rows:
        v = float(r["value"])
        readings.append({
            "timestamp": r["timestamp"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "value": round(v, 3),
            "breached": (crit is not None and v >= crit),
        })

    # Summary stats over the same window (independent of `order`/`limit`
    # so tail-truncation doesn't distort min/max).
    summary_row = await conn.fetchrow(
        f"""
        SELECT
            MIN(value)::float AS lo,
            MAX(value)::float AS hi,
            AVG(value)::float AS mean,
            COUNT(*)          AS n,
            MAX(CASE WHEN value >= $3 THEN timestamp END) AS last_breach
        FROM sensor_readings
        WHERE machine_id = $1 AND sensor_type = $2
          AND timestamp > (SELECT MAX(timestamp) FROM sensor_readings)
                          - INTERVAL '{window_days} days'
        """,
        machine_id, sensor_type, crit if crit is not None else 1e18,
    )
    breach_count_7d = await conn.fetchval(
        """
        SELECT COUNT(*) FROM sensor_readings
        WHERE machine_id = $1 AND sensor_type = $2
          AND value >= $3
          AND timestamp > (SELECT MAX(timestamp) FROM sensor_readings)
                          - INTERVAL '7 days'
        """,
        machine_id, sensor_type, crit if crit is not None else 1e18,
    ) or 0

    return {
        "machine_id": machine_id,
        "component_id": component_id,
        "sensor_type": sensor_type,
        "threshold_critical": crit,
        "threshold_warning": warn,
        "unit": unit,
        "window_days": window_days,
        "order": order,
        "readings": readings,
        "summary": {
            "min": round(summary_row["lo"], 3) if summary_row["lo"] is not None else None,
            "max": round(summary_row["hi"], 3) if summary_row["hi"] is not None else None,
            "avg": round(summary_row["mean"], 3) if summary_row["mean"] is not None else None,
            "count": int(summary_row["n"] or 0),
            "last_breach_at": (
                summary_row["last_breach"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if summary_row["last_breach"] else None
            ),
            "breach_count_last_7d": int(breach_count_7d),
        },
    }


async def tool_get_component_root_cause(conn: asyncpg.Connection, args: dict) -> dict:
    machine_id = args.get("machine_id")
    component_id = args.get("component_id")
    if not machine_id or machine_id not in VALID_MACHINE_IDS:
        raise ValueError(f"invalid machine_id '{machine_id}'")
    if not component_id or component_id not in VALID_COMPONENT_IDS:
        raise ValueError(f"invalid component_id '{component_id}'")

    sensors = _component_sensors_for(component_id)
    if not sensors:
        raise ValueError(f"no sensors known for component '{component_id}'")

    drivers: list[dict] = []
    for s in sensors:
        crit = SENSOR_THRESHOLDS.get(s, {}).get("critical")
        if crit is None:
            continue  # skip sensors without a defined threshold

        latest_v, latest_ts = await _latest_value(conn, machine_id, s)
        max_v, _ = await _max_value_in_window(conn, machine_id, s, window_days=365)
        if latest_v is None:
            continue

        # Headroom: how much the LATEST reading is above critical, as a
        # percent of the threshold. Positive = breaching now.
        headroom_pct = round(100.0 * (latest_v - crit) / crit, 1)

        last_breach_at = await conn.fetchval(
            "SELECT MAX(timestamp) FROM sensor_readings "
            "WHERE machine_id = $1 AND sensor_type = $2 AND value >= $3",
            machine_id, s, crit,
        )
        breach_count_7d = await conn.fetchval(
            """
            SELECT COUNT(*) FROM sensor_readings
            WHERE machine_id = $1 AND sensor_type = $2 AND value >= $3
              AND timestamp > (SELECT MAX(timestamp) FROM sensor_readings)
                              - INTERVAL '7 days'
            """,
            machine_id, s, crit,
        ) or 0

        unit = (SENSOR_META.get(s) or (None, ""))[1]
        drivers.append({
            "sensor_type": s,
            "current_value": round(latest_v, 3),
            "max_value_last_year": round(max_v, 3) if max_v is not None else None,
            "threshold_critical": crit,
            "threshold_warning": SENSOR_THRESHOLDS.get(s, {}).get("warning"),
            "unit": unit,
            "headroom_percent": headroom_pct,
            "last_breach_at": (
                last_breach_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if last_breach_at else None
            ),
            "breach_count_last_7d": int(breach_count_7d),
        })

    if not drivers:
        return {
            "machine_id": machine_id,
            "component_id": component_id,
            "primary_driver": None,
            "contributing_drivers": [],
            "explanation_summary": (
                f"No threshold-bearing sensors on {component_id}; cannot identify a root-cause sensor."
            ),
        }

    # Rank: a sensor is "primary" if its max-recent value is most over
    # threshold (max_value_last_year / critical). This surfaces both
    # currently-breaching sensors AND historical incidents that drive
    # the model's persistent risk score.
    def _rank_key(d: dict) -> tuple[int, float]:
        max_v = d.get("max_value_last_year") or 0.0
        crit = d["threshold_critical"]
        breached = 1 if d["last_breach_at"] else 0
        return (breached, (max_v / crit) if crit else 0.0)

    drivers.sort(key=_rank_key, reverse=True)
    primary = drivers[0]
    contributing = drivers[1:4]  # up to 3 contributing

    # Compose a one-sentence narrative the model can paraphrase or quote.
    if primary["last_breach_at"]:
        # Historical or current breach
        explanation = (
            f"{primary['sensor_type']} on {machine_id}/{component_id} reached "
            f"{primary['max_value_last_year']} {primary['unit']} "
            f"(critical threshold {primary['threshold_critical']} {primary['unit']}); "
            f"last breach {primary['last_breach_at']}, "
            f"{primary['breach_count_last_7d']} breaches in the last 7 days."
        )
    else:
        explanation = (
            f"No sensor on {component_id} has yet crossed its critical threshold; "
            f"closest is {primary['sensor_type']} at {primary['current_value']} "
            f"{primary['unit']} vs {primary['threshold_critical']} critical "
            f"({primary['headroom_percent']:+}% headroom)."
        )

    return {
        "machine_id": machine_id,
        "component_id": component_id,
        "primary_driver": primary,
        "contributing_drivers": contributing,
        "explanation_summary": explanation,
    }


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------

_DISPATCH = {
    "list_machines":             tool_list_machines,
    "get_machine_risk":          tool_get_machine_risk,
    "get_machine_detail":        tool_get_machine_detail,
    "list_alerts":               tool_list_alerts,
    "get_alert":                 tool_get_alert,
    "get_forecast":              tool_get_forecast,
    "get_demand_drivers":        tool_get_demand_drivers,
    "get_fleet_kpis":            tool_get_fleet_kpis,
    "get_sensor_readings":       tool_get_sensor_readings,
    "get_component_root_cause":  tool_get_component_root_cause,
}


async def execute_tool(name: str, args: dict, conn: asyncpg.Connection) -> dict:
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"unknown tool '{name}'")
    return await fn(conn, args or {})
