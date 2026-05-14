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


# Descriptions matching any of these substrings are status updates the
# operator doesn't need to triage ("everything's fine" pings). They stay
# in the DB and in the response (so audits + counts are honest), just
# flagged so the frontend can hide them behind a toggle. Matched
# case-insensitively against the alarm description.
INFORMATIONAL_PATTERNS = [
    "within band",
    "within range",
    "stable",
    "normal range",
    "normal",
    "recovered",
    "setpoint reached",
    "as expected",
    "operating nominally",
    "no fault detected",
]


def is_informational(description: str) -> bool:
    """A description is informational if it matches one of the patterns
    above. Returned independently of tier — the caller combines both
    signals (only tier=healthy + informational counts as 'safe to hide')."""
    if not description:
        return False
    desc_lower = description.lower()
    return any(p in desc_lower for p in INFORMATIONAL_PATTERNS)


# Tier ranking used to pick the "headline" alarm in a grouped row. Lower
# index = more severe = wins. `info` here is the legacy alarm-severity
# value (only used as a fallback when an alert dict somehow lacks `tier`).
_TIER_RANK = {"critical": 0, "warning": 1, "watch": 2, "healthy": 3, "info": 4}

# Original-alarm severity ranking — every event in a bucket has the same
# `tier` (it's the component's live ML score), so to break the tie we
# fall back to what the alarm originally fired as. critical > warning > info.
_ORIG_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


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


async def count_active_buckets_for_machine(
    conn: asyncpg.Connection, machine_id: str,
) -> int:
    """Count of grouped (component) buckets for `machine_id` whose
    collapsed bucket status is 'active' — i.e. the same number shown by
    the "Active" tab on the Alerts page when filtered to this machine.

    Source of truth for both the Overview machine-card "N active alerts"
    pill and the chatbot's `list_machines` tool. Pre-F2 these places
    used raw `COUNT(*) FROM alarm_events WHERE resolved_at IS NULL`,
    which inflated the count with stale rows, informational recovery
    messages, and rows the operator had already acknowledged/scheduled —
    so the same machine showed "23 active alerts" on Overview but "4"
    on the Alerts page. This helper applies the F2 grouping + bucket-
    status precedence so both surfaces agree exactly.
    """
    alerts, _ = await list_alerts(
        conn, machine_id=machine_id, include_resolved=True,
    )
    grouped = group_alerts_by_component(alerts)
    return sum(
        1 for g in grouped
        if (g.get("_status") or g.get("status") or "active") == "active"
    )


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
        score, _row_tier, window = risk_by_pair[(r["machine_id"], comp)]
        # Compute the live 4-tier classification from the current ML score.
        # The seeded `severity` column reflects what the alarm originally
        # fired as (info / warning / critical) — kept for audit and as
        # `original_severity` so the UI can surface "originally fired as
        # info" when the model has since moved the row.
        live_tier = tier_for(score)
        title_short = r["description"].split(".")[0][:120]

        # An alert is "informational" when it both (a) reads as a benign
        # status update AND (b) lives in a healthy component. A critical
        # tier on a row whose description says "within band" is still
        # critical — the model is telling us something the description
        # doesn't.
        info_flag = (live_tier == "healthy") and is_informational(r["description"])
        alert = {
            "alert_id": _alert_id_from_alarm(r["alarm_id"]),
            "machine_id": r["machine_id"],
            "component_id": comp,
            "severity": r["severity"],            # legacy 3-value (info/warning/critical)
            "tier": live_tier,                    # live 4-value (healthy/watch/warning/critical)
            "original_severity": r["severity"],   # alias of severity, named for clarity
            "is_informational": info_flag,
            "timestamp": r["timestamp"],          # kept for grouping aggregation; stripped from non-grouped responses
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
        counts[a["tier"]] += 1

    return alerts, counts


# ---------------------------------------------------------------------------
# Group-by-component aggregation (Phase F2)
# ---------------------------------------------------------------------------

# Precedence for collapsing a bucket's many event statuses down to one
# "group status" that drives the StatusTabs counts on the Alerts page.
# Order: any triage action (scheduled / acknowledged / snoozed) wins
# over raw `active` (because the operator already worked the bucket);
# `active` wins over `resolved` (a single still-open alarm keeps the
# bucket open). Only when EVERY event is resolved does the bucket read
# as resolved.
#
# Without this, the head-event sort below picks the highest-severity
# event for the headline and inherits that one event's status — which
# made every bucket look "resolved" whenever a long-resolved critical
# alarm dominated the severity sort, even though newer active rows for
# the same component existed in the DB.
_GROUP_STATUS_PRIORITY = {
    "scheduled":    0,
    "acknowledged": 1,
    "snoozed":      2,
    "active":       3,
    "resolved":     4,
}


def _bucket_status(events: list[dict]) -> str:
    best = "active"
    best_rank = 999
    for e in events:
        s = e.get("_status") or e.get("status") or "active"
        rank = _GROUP_STATUS_PRIORITY.get(s, 999)
        if rank < best_rank:
            best_rank = rank
            best = s
    return best


def _bucket_status_event(events: list[dict], bucket_status: str) -> Optional[dict]:
    """Pick the most recently status-changed event whose status matches
    the bucket's collapsed status — so the grouped row carries the right
    status_changed_at / status_changed_by / status_metadata (e.g. the
    scheduled_date + technician for a scheduled bucket)."""
    matches = [
        e for e in events
        if (e.get("_status") or e.get("status") or "active") == bucket_status
    ]
    if not matches:
        return None
    def _key(e):
        ts = e.get("status_changed_at") or e.get("timestamp")
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return datetime.min.replace(tzinfo=timezone.utc)
    return max(matches, key=_key)


def group_alerts_by_component(alerts: list[dict]) -> list[dict]:
    """Bucket per-row alerts by (machine_id, component_id) and emit one
    grouped row per bucket.

    Aggregation rules:
      - tier:        max-severity in the group (critical > warning > watch > healthy)
      - title/desc:  taken from the highest-tier alarm in the group
      - timestamps:  first_triggered_at = oldest, latest_triggered_at = newest
      - is_informational: True only when EVERY event in the bucket is
        informational. One real alarm in a 4-event bucket flips it to False.
      - underlying_events: list of every event in the group (oldest-first)
        so the frontend expand toggle can reveal them all.

    The grouped rows preserve fields the AlertCard/badge needs (severity,
    tier, original_severity, risk_score, recommended_action, cost, …)
    sourced from the headline event so existing UI code still renders.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for a in alerts:
        key = (a["machine_id"], a["component_id"])
        buckets.setdefault(key, []).append(a)

    grouped: list[dict] = []
    for (machine_id, component_id), events in buckets.items():
        # Pick the "headline" event for the bucket. Every event here has
        # the same `tier` (the component's live ML score), so the tier
        # field alone collapses to newest-first — which is wrong, because
        # the newest event is often a benign recovery message ("Stock
        # temperature recovered to normal range") even on a critical
        # group. Sort instead by:
        #
        #   1. is_informational ASC                    real alarms before info pings
        #   2. description-matches-INFO-patterns ASC   push "recovered/within band/stable"
        #                                              to the back even when the
        #                                              info_flag was suppressed because
        #                                              the component is critical-tier
        #   3. _ORIG_SEV_RANK[original_severity] ASC   critical > warning > info
        #   4. _TIER_RANK[tier] ASC                    no-op within a bucket; cheap tiebreak
        #   5. timestamp DESC                          within the same severity, newest wins
        def _head_key(e):
            desc_is_info = is_informational(e.get("description", ""))
            ts = e.get("timestamp")
            ts_score = -(ts.timestamp()) if ts else 0
            return (
                1 if e.get("is_informational", False) else 0,
                1 if desc_is_info else 0,
                _ORIG_SEV_RANK.get(e.get("original_severity"), 9),
                _TIER_RANK.get(e.get("tier"), 9),
                ts_score,
            )

        events_by_severity = sorted(events, key=_head_key)
        head = events_by_severity[0]

        # Underlying-events list, oldest-first (chronological for the
        # expand panel). Strip down to the fields the modal needs.
        events_by_time = sorted(
            events,
            key=lambda e: (e["timestamp"].timestamp() if e.get("timestamp") else 0),
        )
        underlying = [
            {
                "alarm_id":         _alarm_id_from_alert(e["alert_id"]),
                "alert_id":         e["alert_id"],
                "description":      e["description"],
                "severity":         e["severity"],
                "tier":             e["tier"],
                "timestamp":        _iso(e["timestamp"]) if e.get("timestamp") else None,
                "is_informational": e.get("is_informational", False),
            }
            for e in events_by_time
        ]

        first_ts = events_by_time[0]["timestamp"]
        latest_ts = events_by_time[-1]["timestamp"]

        all_informational = all(e.get("is_informational", False) for e in events)

        # Collapsed bucket status + its source event (for status_metadata).
        _bucket_st = _bucket_status(events)
        _st_evt = _bucket_status_event(events, _bucket_st)

        grouped.append({
            "alert_id":          head["alert_id"],
            "machine_id":        machine_id,
            "component_id":      component_id,
            # Surface the headline alarm's classification — the badge
            # already reads `tier`, so this row renders correctly without
            # any frontend-side max() logic.
            "severity":          head["severity"],
            "tier":              head["tier"],
            "original_severity": head["original_severity"],
            "risk_score":        head["risk_score"],
            "title":             head["title"],
            "description":       head["description"],
            "predicted_failure_window_hours": head["predicted_failure_window_hours"],
            "recommended_action":             head["recommended_action"],
            "estimated_cost_if_unaddressed_usd": head["estimated_cost_if_unaddressed_usd"],
            # Bucket-level aggregates
            "first_triggered_at":  _iso(first_ts) if first_ts else None,
            "latest_triggered_at": _iso(latest_ts) if latest_ts else None,
            "event_count":         len(events),
            "alarm_ids":           [u["alarm_id"] for u in underlying],
            "underlying_events":   underlying,
            "is_informational":    all_informational,
            # Status fields are collapsed across the WHOLE bucket via the
            # precedence rule (scheduled > acknowledged > snoozed > active
            # > resolved), not pulled from the head. That way one old
            # resolved critical alarm can't drag a still-active bucket
            # into the Resolved tab.
            "status":              _bucket_st,
            "status_changed_at":   (_st_evt.get("status_changed_at") if _st_evt else None),
            "status_changed_by":   (_st_evt.get("status_changed_by") if _st_evt else None),
            "status_metadata":     (_st_evt.get("status_metadata") if _st_evt else {}) or {},
            "_status":             _bucket_st,
            "acknowledged":        _bucket_st in ("acknowledged", "scheduled", "snoozed", "resolved"),
            "created_at":          _iso(first_ts) if first_ts else head.get("created_at"),
        })

    # Sort grouped rows the same way the per-row list was sorted by
    # default — most-severe first, tie-broken by risk_score desc.
    grouped.sort(key=lambda g: (_TIER_RANK.get(g["tier"], 9), -g["risk_score"]))
    return grouped


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
