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

from ..db import get_pool
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


VALID_STATUSES = ("active", "acknowledged", "scheduled", "snoozed", "resolved")
NON_TERMINAL_STATUSES = ("active", "acknowledged", "scheduled", "snoozed")


# ---------------------------------------------------------------------------
# Per-(machine, component) risk cache — closes audit finding
# "alerts-list-15s-latency". Computing risk per alert row is the bottleneck:
# a typical /alerts response carries 200 rows but only ~24 unique
# (machine_id, component_id) pairs. We resolve each pair at most once per
# request (per-call memoisation) and reuse for `_TTL_SECONDS` across
# requests so a Browse-Tab refresh inside the same minute is essentially free.
# ---------------------------------------------------------------------------
import time as _time

_RISK_TTL_SECONDS = 60
_RiskCacheKey = tuple[str, str]
_risk_cache: dict[_RiskCacheKey, tuple[float, int, str, "Optional[int]"]] = {}


async def _resolve_risk_with_ttl(
    pool: "asyncpg.Pool", machine_id: str, component_id: str,
) -> tuple[int, str, "Optional[int]"]:
    """Cache wrapper around `component_risk` keyed on (machine, component)
    with a `_RISK_TTL_SECONDS` TTL. The list endpoint calls this per
    unique pair instead of per row.

    On cache miss this acquires its own connection from the pool — it
    must NOT reuse the caller's connection, because the list endpoint
    fans these calls out through `asyncio.gather` and asyncpg
    connections are not safe for concurrent use (one query in flight
    per connection). Sharing a connection here trips
    `InterfaceError: cannot perform operation: another operation is in
    progress` and turns /alerts into a 500.
    """
    now = _time.time()
    cached = _risk_cache.get((machine_id, component_id))
    if cached is not None:
        ts, score, tier, window = cached
        if now - ts < _RISK_TTL_SECONDS:
            return score, tier, window
    async with pool.acquire() as conn:
        score, tier, window = await component_risk(conn, machine_id, component_id)
    _risk_cache[(machine_id, component_id)] = (now, score, tier, window)
    return score, tier, window


def reset_risk_cache() -> None:
    """Test / admin hook — wipe the (machine, component) risk cache."""
    _risk_cache.clear()


async def warm_risk_cache(pool: "asyncpg.Pool") -> int:
    """Pre-populate the risk cache for every (machine, component) pair in
    the fleet. Called from the FastAPI lifespan on startup as a
    fire-and-forget task so the first /alerts request hits warm data
    instead of paying ~7s of ML inference. Returns the number of pairs
    successfully resolved.

    Takes the pool (not a connection) because each pair is resolved
    concurrently via `asyncio.gather` — see `_resolve_risk_with_ttl`
    for the asyncpg concurrency rationale.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT machine_id, component_id FROM components ORDER BY machine_id, component_id"
        )
    pairs = [(r["machine_id"], r["component_id"]) for r in rows]
    if not pairs:
        return 0
    import asyncio
    results = await asyncio.gather(
        *[_resolve_risk_with_ttl(pool, m, c) for m, c in pairs],
        return_exceptions=True,
    )
    return sum(1 for r in results if not isinstance(r, BaseException))


async def list_alerts(
    conn: asyncpg.Connection,
    severity: Optional[str] = None,
    machine_id: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    status: Optional[str] = None,
    sort: str = "severity",
    include_resolved: bool = False,
) -> tuple[list[dict], dict[str, int]]:
    """Build alerts from `alarm_events`. Returns (alerts, counts_by_tier).

    By default returns only non-terminal rows (active/acknowledged/
    scheduled/snoozed). Pass `status='resolved'` (or `include_resolved=True`)
    to include resolved alerts.
    """
    sql = """
        SELECT alarm_id, machine_id, timestamp, severity, description,
               status, status_changed_at, status_changed_by, status_metadata
        FROM alarm_events
        WHERE 1 = 1
    """
    params: list = []
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status '{status}'")
        params.append(status)
        sql += f" AND status = ${len(params)}"
    elif not include_resolved:
        sql += " AND status <> 'resolved'"
    if severity:
        params.append(severity)
        sql += f" AND severity = ${len(params)}"
    if machine_id:
        params.append(machine_id)
        sql += f" AND machine_id = ${len(params)}"
    sql += " ORDER BY timestamp DESC LIMIT 200"

    rows = await conn.fetch(sql, *params)

    # Pass 1: classify every row, collect the unique (machine, component)
    # pairs that need a risk score. The per-request memo means the cache
    # we hit below resolves *each unique pair* at most once even if 50
    # rows reference the same Yankee on Al-Nakheel.
    classified: list[tuple] = []        # (row, comp, status_str)
    pairs_needed: set[tuple[str, str]] = set()
    for r in rows:
        comp = _attribute_component(r["description"])
        st = r["status"] or "active"
        classified.append((r, comp, st))
        pairs_needed.add((r["machine_id"], comp))

    # Pass 2: resolve risk for each unique pair (TTL-cached across requests).
    # 200 alert rows -> typically <=24 calls cold, 0 calls warm. Pairs are
    # resolved concurrently so the ML inference + DB feature build for one
    # pair overlaps with the others; cuts cold latency by ~3-5x. ML libs
    # release the GIL during numpy-heavy work so this is real parallelism.
    #
    # NB: hand the POOL — not the route's `conn` — into the gather. asyncpg
    # connections are single-query-at-a-time; each coroutine here must
    # acquire its own connection or they trip `InterfaceError: cannot
    # perform operation: another operation is in progress`. The route's
    # `conn` stays live above for the initial fetch and is released after
    # this function returns.
    pairs_list = sorted(pairs_needed)
    pool = get_pool()
    import asyncio
    risk_results = await asyncio.gather(*[
        _resolve_risk_with_ttl(pool, m, c) for m, c in pairs_list
    ])
    risk_by_pair: dict[tuple[str, str], tuple[int, str, "Optional[int]"]] = {
        pair: result for pair, result in zip(pairs_list, risk_results)
    }

    # Pass 3: build the alert payloads.
    alerts: list[dict] = []
    for r, comp, st in classified:
        score, tier, window = risk_by_pair[(r["machine_id"], comp)]
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
            "acknowledged": st in ("acknowledged", "scheduled", "snoozed", "resolved"),
            "status": st,
            "status_changed_at": _iso(r["status_changed_at"]) if r["status_changed_at"] else None,
            "status_changed_by": r["status_changed_by"],
            "status_metadata": _decode_metadata(r["status_metadata"]),
            # Surface as a top-level "_status" too: the existing frontend
            # filters on alert._status -- keeping that field populated lets
            # the screen tabs (Active/Ack/Scheduled/Snoozed/Resolved)
            # pivot off real DB state instead of localStorage.
            "_status": st,
        }
        alerts.append(alert)

    if acknowledged is not None:
        alerts = [a for a in alerts if a["acknowledged"] == acknowledged]

    sev_order = {"critical": 0, "warning": 1, "info": 2}
    if sort == "severity":
        alerts.sort(key=lambda a: (sev_order.get(a["severity"], 9), -a["risk_score"]))
    elif sort == "risk_score":
        alerts.sort(key=lambda a: -a["risk_score"])
    else:  # created_at
        alerts.sort(key=lambda a: a["created_at"], reverse=True)

    counts: dict[str, int] = {"critical": 0, "warning": 0, "watch": 0, "healthy": 0}
    for a in alerts:
        counts[tier_for(a["risk_score"])] += 1

    return alerts, counts


async def get_alert(conn: asyncpg.Connection, alert_id: str) -> Optional[dict]:
    alarm_id = _alarm_id_from_alert(alert_id)
    row = await conn.fetchrow(
        """
        SELECT alarm_id, machine_id, timestamp, severity, description,
               status, status_changed_at, status_changed_by, status_metadata
        FROM alarm_events
        WHERE alarm_id = $1
        """,
        alarm_id,
    )
    if not row:
        return None
    comp = _attribute_component(row["description"])
    score, tier, window = await component_risk(conn, row["machine_id"], comp)
    st = row["status"] or "active"
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
        "acknowledged": st in ("acknowledged", "scheduled", "snoozed", "resolved"),
        "status": st,
        "status_changed_at": _iso(row["status_changed_at"]) if row["status_changed_at"] else None,
        "status_changed_by": row["status_changed_by"],
        "status_metadata": _decode_metadata(row["status_metadata"]),
        "_status": st,
    }


# ---------------------------------------------------------------------------
# Status mutation — persists the alert through its triage workflow.
# ---------------------------------------------------------------------------

async def set_alert_status(
    conn: asyncpg.Connection,
    alert_id: str,
    *,
    new_status: str,
    changed_by: str,
    metadata: Optional[dict] = None,
    mark_resolved_at: bool = False,
) -> Optional[dict]:
    """Update one alarm_events row. Returns the updated alert payload (same
    shape as `get_alert`) or None if the alert doesn't exist."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status '{new_status}'")
    alarm_id = _alarm_id_from_alert(alert_id)

    import json
    sql = """
        UPDATE alarm_events
        SET status = $2,
            status_changed_at = NOW(),
            status_changed_by = $3,
            status_metadata = $4::jsonb,
            resolved_at = CASE
                WHEN $5::bool THEN COALESCE(resolved_at, NOW())
                ELSE resolved_at
            END
        WHERE alarm_id = $1
        RETURNING alarm_id
    """
    updated = await conn.fetchval(
        sql,
        alarm_id, new_status, changed_by,
        json.dumps(metadata or {}, default=str),
        mark_resolved_at,
    )
    if not updated:
        return None
    return await get_alert(conn, alert_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_metadata(raw) -> dict:
    """`status_metadata` arrives from asyncpg as either a parsed dict (rare)
    or a JSON string (typical). Normalise to a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        import json
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}


def _alert_id_from_alarm(alarm_id: str) -> str:
    """alarm_id 'alm-2026-04-25-0017' -> alert_id 'alt-2026-04-25-0017'."""
    if alarm_id.startswith("alm-"):
        return "alt-" + alarm_id[4:]
    return alarm_id


def _alarm_id_from_alert(alert_id: str) -> str:
    if alert_id.startswith("alt-"):
        return "alm-" + alert_id[4:]
    return alert_id
