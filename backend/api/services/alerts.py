"""Alerts service.

Alerts (the items shown on the /alerts page) are *synthesised* from the
combination of:
  - unresolved alarm_events
  - high-risk components

The contract Alert object (alert_id, title, predicted_failure_window_hours,
recommended_action, estimated_cost_if_unaddressed_usd, acknowledged) is
richer than the raw alarm row, so we synthesise the remaining fields
deterministically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import asyncpg

from .constants import COMPONENT_ORDER, tier_for
from .risk import component_risk

# Description-keyword → component_id mapping (alarm_events.description is free-text).
_DESCRIPTION_KEYWORDS = [
    ("yankee bearing 3", "yankee"),
    ("yankee bearing 2", "yankee"),
    ("yankee bearing 1", "yankee"),
    ("yankee surface",   "yankee"),
    ("yankee",           "yankee"),
    ("creping blade",    "yankee"),
    ("steam pressure",   "yankee"),
    ("visconip",         "visconip"),
    ("nip pressure",     "visconip"),
    ("felt moisture",    "visconip"),
    ("aircap",           "aircap"),
    ("burner",           "aircap"),
    ("inlet temperature", "aircap"),
    ("headbox",          "headbox"),
    ("stock temperature", "headbox"),
    ("softreel",         "softreel"),
    ("tension",          "softreel"),
    ("rewinder",         "rewinder"),
    ("speed",            "rewinder"),
]

# Component → cost of an unaddressed failure (USD). Yankee is the highest at
# $20K/hr × 24h = $480k (lines up with the contract example).
_COST_BY_COMPONENT = {
    "yankee":   480_000,
    "visconip": 120_000,
    "aircap":    60_000,
    "headbox":   45_000,
    "softreel":  25_000,
    "rewinder":  25_000,
}

_RECOMMENDED_BY_COMPONENT = {
    "yankee":   "Schedule bearing replacement in next planned downtime window. Stockpile spare bearing set BR-7842.",
    "visconip": "Plan ViscoNip felt change within 7 days; verify spare felt in stores.",
    "aircap":   "Inspect AirCap burner and inlet ducting at next changeover.",
    "headbox":  "Check headbox screens and stock temperature loop.",
    "softreel": "Inspect SoftReel tension transducer and bearings.",
    "rewinder": "Check rewinder drive and emergency-stop circuit.",
}


def _attribute_component(description: str) -> str:
    desc = (description or "").lower()
    for keyword, comp in _DESCRIPTION_KEYWORDS:
        if keyword in desc:
            return comp
    return "yankee"  # default to Yankee — the headline component


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def list_alerts(
    conn: asyncpg.Connection,
    severity: Optional[str] = None,
    machine_id: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    sort: str = "severity",
) -> tuple[list[dict], dict[str, int]]:
    """Build alerts from unresolved alarm_events. Returns (alerts, counts_by_tier)."""
    sql = """
        SELECT alarm_id, machine_id, timestamp, severity, description
        FROM alarm_events
        WHERE resolved_at IS NULL
    """
    params: list = []
    if severity:
        params.append(severity)
        sql += f" AND severity = ${len(params)}"
    if machine_id:
        params.append(machine_id)
        sql += f" AND machine_id = ${len(params)}"
    sql += " ORDER BY timestamp DESC LIMIT 200"

    rows = await conn.fetch(sql, *params)

    alerts: list[dict] = []
    for r in rows:
        comp = _attribute_component(r["description"])
        score, tier, window = await component_risk(conn, r["machine_id"], comp)
        title_short = r["description"].split(".")[0][:120]

        alert = {
            "alert_id": _alert_id_from_alarm(r["alarm_id"]),
            "machine_id": r["machine_id"],
            "component_id": comp,
            "severity": r["severity"],
            "risk_score": score,
            "title": title_short or "Component alert",
            "description": r["description"],
            "predicted_failure_window_hours": window,
            "recommended_action": _RECOMMENDED_BY_COMPONENT.get(comp, "Investigate and schedule maintenance."),
            "estimated_cost_if_unaddressed_usd": _COST_BY_COMPONENT.get(comp, 25_000),
            "created_at": _iso(r["timestamp"]),
            "acknowledged": False,
        }
        alerts.append(alert)

    if acknowledged is not None:
        alerts = [a for a in alerts if a["acknowledged"] == acknowledged]

    # Sort
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    if sort == "severity":
        alerts.sort(key=lambda a: (sev_order.get(a["severity"], 9), -a["risk_score"]))
    elif sort == "risk_score":
        alerts.sort(key=lambda a: -a["risk_score"])
    else:  # created_at
        alerts.sort(key=lambda a: a["created_at"], reverse=True)

    # Counts by tier
    counts: dict[str, int] = {"critical": 0, "warning": 0, "watch": 0, "healthy": 0}
    for a in alerts:
        counts[tier_for(a["risk_score"])] += 1

    return alerts, counts


async def get_alert(conn: asyncpg.Connection, alert_id: str) -> Optional[dict]:
    alarm_id = _alarm_id_from_alert(alert_id)
    row = await conn.fetchrow(
        """
        SELECT alarm_id, machine_id, timestamp, severity, description
        FROM alarm_events
        WHERE alarm_id = $1
        """,
        alarm_id,
    )
    if not row:
        return None
    comp = _attribute_component(row["description"])
    score, tier, window = await component_risk(conn, row["machine_id"], comp)
    return {
        "alert_id": alert_id,
        "machine_id": row["machine_id"],
        "component_id": comp,
        "severity": row["severity"],
        "risk_score": score,
        "title": row["description"].split(".")[0][:120],
        "description": row["description"],
        "predicted_failure_window_hours": window,
        "recommended_action": _RECOMMENDED_BY_COMPONENT.get(comp, "Investigate and schedule maintenance."),
        "estimated_cost_if_unaddressed_usd": _COST_BY_COMPONENT.get(comp, 25_000),
        "created_at": _iso(row["timestamp"]),
        "acknowledged": False,
    }


def _alert_id_from_alarm(alarm_id: str) -> str:
    """alarm_id 'alm-2026-04-25-0017' -> alert_id 'alt-2026-04-25-0017'."""
    if alarm_id.startswith("alm-"):
        return "alt-" + alarm_id[4:]
    return alarm_id


def _alarm_id_from_alert(alert_id: str) -> str:
    if alert_id.startswith("alt-"):
        return "alm-" + alert_id[4:]
    return alert_id
