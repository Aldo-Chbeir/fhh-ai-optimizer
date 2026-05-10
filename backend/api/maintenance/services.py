"""DB layer for user_maintenance_entries — pool-first asyncpg.

The Calendar feed source `_query_user_maintenance` (in
backend/api/services/calendar.py) reads through `list_entries_in_date_range`
so the unified feed can fan out concurrently with the other 5 sources.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

import asyncpg


def _row(r) -> dict:
    return {
        "id":               str(r["id"]),
        "user_id":          str(r["user_id"]),
        "machine_id":       r["machine_id"],
        "component_id":     r["component_id"],
        "maintenance_type": r["maintenance_type"],
        "work_description": r["work_description"],
        "cost_usd":         float(r["cost_usd"]) if r["cost_usd"] is not None else None,
        "duration_hours":   float(r["duration_hours"]) if r["duration_hours"] is not None else None,
        "technician_name":  r["technician_name"],
        "performed_at":     r["performed_at"],
        "created_at":       r["created_at"],
    }


async def create_entry(
    pool: asyncpg.Pool,
    *,
    user_id: UUID,
    machine_id: str,
    maintenance_type: str,
    work_description: str,
    technician_name: str,
    cost_usd: Optional[float] = None,
    duration_hours: Optional[float] = None,
    performed_at: Optional[datetime] = None,
    component_id: Optional[str] = None,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_maintenance_entries (
                user_id, machine_id, component_id, maintenance_type,
                work_description, cost_usd, duration_hours,
                technician_name, performed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    COALESCE($9, NOW()))
            RETURNING *
            """,
            user_id, machine_id, component_id, maintenance_type,
            work_description, cost_usd, duration_hours,
            technician_name, performed_at,
        )
    return _row(row)


async def list_entries_for_machine(
    pool: asyncpg.Pool, machine_id: str,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM user_maintenance_entries
            WHERE machine_id = $1
            ORDER BY performed_at DESC, created_at DESC
            """,
            machine_id,
        )
    return [_row(r) for r in rows]


async def list_entries_in_date_range(
    pool: asyncpg.Pool, start: date, end: date,
) -> list[dict]:
    """Used by the Calendar unified feed. Date filter is on `performed_at`
    cast to a date, so an entry logged at 23:59 UTC on `end` is included."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM user_maintenance_entries
            WHERE performed_at::date BETWEEN $1 AND $2
            ORDER BY performed_at ASC
            """,
            start, end,
        )
    return [_row(r) for r in rows]


async def get_entry(
    pool: asyncpg.Pool, entry_id: UUID,
) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_maintenance_entries WHERE id = $1", entry_id,
        )
    return _row(row) if row else None


async def delete_entry(
    pool: asyncpg.Pool, entry_id: UUID, user_id: UUID,
) -> bool:
    """Owner-only delete. Returns True iff a row was actually removed.

    Same enumeration-leak guard as chat_memory.delete_user_conversation —
    if the row exists but isn't yours, we silently return False so the
    router can 404 with the same message as 'doesn't exist'.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_maintenance_entries WHERE id = $1 AND user_id = $2",
            entry_id, user_id,
        )
    return result.endswith(" 1")
