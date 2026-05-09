"""DB layer for calendar_events_custom + the unified Calendar-tab feed.

Note: calendar_events_custom has NO ON UPDATE trigger. Every UPDATE here
MUST include `updated_at = NOW()` explicitly.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, timezone
from typing import Any, Optional

import asyncpg

from ..db.pool import get_pool


# ---------------------------------------------------------------------------
# Custom-event CRUD
# ---------------------------------------------------------------------------

def _generate_event_id() -> str:
    return f"cal-evt-{uuid.uuid4().hex[:8]}"


def _ts(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time_iso(t) -> Optional[str]:
    return t.isoformat() if t is not None else None


def _row_to_event(r) -> dict:
    return {
        "event_id":         r["event_id"],
        "title":            r["title"],
        "event_date":       r["event_date"].isoformat(),
        "event_time":       _time_iso(r["event_time"]),
        "duration_minutes": r["duration_minutes"],
        "machine_id":       r["machine_id"],
        "event_type":       r["event_type"],
        "notes":            r["notes"],
        "created_by":       r["created_by"],
        "created_at":       _ts(r["created_at"]),
        "updated_at":       _ts(r["updated_at"]),
    }


async def create_event(conn: asyncpg.Connection, body: dict) -> dict:
    event_id = _generate_event_id()
    row = await conn.fetchrow(
        """
        INSERT INTO calendar_events_custom (
            event_id, title, event_date, event_time, duration_minutes,
            machine_id, event_type, notes, created_by
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING *
        """,
        event_id, body["title"], body["event_date"], body.get("event_time"),
        body.get("duration_minutes"), body.get("machine_id"),
        body["event_type"], body.get("notes"), body.get("created_by"),
    )
    return _row_to_event(row)


async def get_event(conn: asyncpg.Connection, event_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT * FROM calendar_events_custom WHERE event_id = $1", event_id,
    )
    return _row_to_event(row) if row else None


async def update_event(
    conn: asyncpg.Connection, event_id: str, body: dict,
) -> Optional[dict]:
    updates: list[str] = []
    params: list[Any] = []
    for col in ("title", "event_date", "event_time", "duration_minutes",
                "machine_id", "event_type", "notes", "created_by"):
        if col in body and body[col] is not None:
            params.append(body[col])
            updates.append(f"{col} = ${len(params)}")
    updates.append("updated_at = NOW()")  # required: no ON UPDATE trigger
    params.append(event_id)
    sql = f"""
        UPDATE calendar_events_custom
        SET {", ".join(updates)}
        WHERE event_id = ${len(params)}
        RETURNING *
    """
    row = await conn.fetchrow(sql, *params)
    return _row_to_event(row) if row else None


async def delete_event(conn: asyncpg.Connection, event_id: str) -> bool:
    result = await conn.execute(
        "DELETE FROM calendar_events_custom WHERE event_id = $1", event_id,
    )
    return result.endswith(" 1")


# ---------------------------------------------------------------------------
# Unified feed (5 sources, fanned out concurrently)
# ---------------------------------------------------------------------------

CAP = 500

SOURCE_ORDER = {
    "alert":                 0,
    "scheduled_maintenance": 1,
    "past_maintenance":      2,
    "material_order":        3,
    "custom":                4,
}


def _decode_metadata(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}


async def _query_alerts(pool: asyncpg.Pool, start: date, end: date) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT alarm_id, machine_id, timestamp, severity, description, status
            FROM alarm_events
            WHERE status IN ('active','acknowledged','snoozed')
              AND timestamp::date BETWEEN $1 AND $2
            ORDER BY timestamp ASC
            LIMIT $3
            """,
            start, end, CAP,
        )
    out = []
    for r in rows:
        alarm_id = r["alarm_id"]
        alert_id = ("alt-" + alarm_id[4:]) if alarm_id.startswith("alm-") else alarm_id
        out.append({
            "source":     "alert",
            "id":         alarm_id,
            "date":       r["timestamp"].astimezone(timezone.utc).date().isoformat(),
            "title":      r["description"],
            "severity":   r["severity"],
            "machine_id": r["machine_id"],
            "status":     r["status"],
            "alert_id":   alert_id,
        })
    return out


async def _query_scheduled(pool: asyncpg.Pool, start: date, end: date) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT alarm_id, machine_id, description, status_metadata
            FROM alarm_events
            WHERE status = 'scheduled'
              AND (status_metadata->>'scheduled_date')::date BETWEEN $1 AND $2
            ORDER BY (status_metadata->>'scheduled_date')::date ASC
            LIMIT $3
            """,
            start, end, CAP,
        )
    out = []
    for r in rows:
        meta = _decode_metadata(r["status_metadata"])
        alarm_id = r["alarm_id"]
        # Same alm- → alt- mapping that services/alerts.py applies, surfaced
        # so the EventDetailModal can display the user-facing alert_id for
        # a scheduled_maintenance row (parity with source='alert' items).
        alert_id = ("alt-" + alarm_id[4:]) if alarm_id.startswith("alm-") else alarm_id
        out.append({
            "source":     "scheduled_maintenance",
            "id":         alarm_id,
            "alert_id":   alert_id,
            "date":       meta.get("scheduled_date"),
            "title":      r["description"],
            "machine_id": r["machine_id"],
            "technician": meta.get("technician"),
            "priority":   meta.get("priority"),
            "notes":      meta.get("notes"),
        })
    return out


async def _query_past_maintenance(pool: asyncpg.Pool, start: date, end: date) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT log_id, machine_id, maintenance_type, date_performed,
                   technician, downtime_hours, cost_usd, notes
            FROM maintenance_logs
            WHERE date_performed BETWEEN $1 AND $2
            ORDER BY date_performed ASC
            LIMIT $3
            """,
            start, end, CAP,
        )
    out = []
    for r in rows:
        mtype = r["maintenance_type"] or "Maintenance"
        out.append({
            "source":         "past_maintenance",
            "id":             r["log_id"],
            "date":           r["date_performed"].isoformat(),
            "title":          mtype.capitalize() + " maintenance",
            "machine_id":     r["machine_id"],
            "technician":     r["technician"],
            "downtime_hours": float(r["downtime_hours"]) if r["downtime_hours"] is not None else None,
            "cost_usd":       float(r["cost_usd"]) if r["cost_usd"] is not None else None,
            "notes":          r["notes"],
        })
    return out


async def _query_material_orders(pool: asyncpg.Pool, start: date, end: date) -> list[dict]:
    """Each material_orders row emits up to TWO feed items: a 'placed' event
    on order_date and an 'arrives' event on expected_arrival_date. Each
    item is included only if its own date falls in [start, end] — but the
    row qualifies for the SQL fetch if EITHER date is in range, so a
    'placed' event still surfaces when the arrival is far outside the
    window (and vice-versa). Both items carry both dates so the detail
    modal can show the full timeline regardless of which one was clicked.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id, sku, market, quantity, unit,
                   order_date, expected_arrival_date,
                   status, notes
            FROM material_orders
            WHERE order_date BETWEEN $1 AND $2
               OR expected_arrival_date BETWEEN $1 AND $2
            ORDER BY order_date ASC
            LIMIT $3
            """,
            start, end, CAP,
        )
    out = []
    for r in rows:
        common = {
            "source":                "material_order",
            "sku":                   r["sku"],
            "market":                r["market"],
            "quantity":              float(r["quantity"]),
            "unit":                  r["unit"],
            "status":                r["status"],
            "notes":                 r["notes"],
            "order_date":            r["order_date"].isoformat(),
            "expected_arrival_date": r["expected_arrival_date"].isoformat(),
        }
        if start <= r["order_date"] <= end:
            out.append({
                **common,
                "id":    f"{r['order_id']}:placed",
                "date":  r["order_date"].isoformat(),
                "title": f"Order placed: {r['sku']}",
            })
        if start <= r["expected_arrival_date"] <= end:
            out.append({
                **common,
                "id":    f"{r['order_id']}:arrives",
                "date":  r["expected_arrival_date"].isoformat(),
                "title": f"Order arrives: {r['sku']}",
            })
    return out


async def _query_custom(pool: asyncpg.Pool, start: date, end: date) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_id, title, event_date, event_time, duration_minutes,
                   machine_id, event_type, notes
            FROM calendar_events_custom
            WHERE event_date BETWEEN $1 AND $2
            ORDER BY event_date ASC
            LIMIT $3
            """,
            start, end, CAP,
        )
    out = []
    for r in rows:
        out.append({
            "source":           "custom",
            "id":               r["event_id"],
            "date":             r["event_date"].isoformat(),
            "title":            r["title"],
            "machine_id":       r["machine_id"],
            "event_type":       r["event_type"],
            "event_time":       _time_iso(r["event_time"]),
            "duration_minutes": r["duration_minutes"],
            "notes":            r["notes"],
        })
    return out


async def get_unified_feed(start: date, end: date) -> tuple[list[dict], bool]:
    """Run the 5 source queries concurrently against the pool. Each
    coroutine acquires its own connection — asyncpg connections aren't
    safe to share across concurrent queries (same constraint as
    services/alerts.py warm-up path)."""
    pool = get_pool()
    results = await asyncio.gather(
        _query_alerts(pool, start, end),
        _query_scheduled(pool, start, end),
        _query_past_maintenance(pool, start, end),
        _query_material_orders(pool, start, end),
        _query_custom(pool, start, end),
    )
    merged: list[dict] = []
    for r in results:
        merged.extend(r)
    merged.sort(key=lambda e: (e.get("date") or "", SOURCE_ORDER.get(e["source"], 99)))
    truncated = len(merged) > CAP
    if truncated:
        merged = merged[:CAP]
    return merged, truncated
