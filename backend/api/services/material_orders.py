"""DB layer for material_orders.

Note: material_orders has NO ON UPDATE trigger. Every UPDATE here MUST
include `updated_at = NOW()` explicitly so the column doesn't go stale.
"""
from __future__ import annotations

import uuid
from datetime import date, timezone
from typing import Any, Optional

import asyncpg


def _generate_order_id() -> str:
    return f"mat-ord-{uuid.uuid4().hex[:8]}"


def _ts(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(r) -> dict:
    return {
        "order_id":              r["order_id"],
        "sku":                   r["sku"],
        "market":                r["market"],
        "quantity":              float(r["quantity"]),
        "unit":                  r["unit"],
        "order_date":            r["order_date"].isoformat(),
        "expected_arrival_date": r["expected_arrival_date"].isoformat(),
        "status":                r["status"],
        "created_by":            r["created_by"],
        "notes":                 r["notes"],
        "created_at":            _ts(r["created_at"]),
        "updated_at":            _ts(r["updated_at"]),
    }


async def create_order(conn: asyncpg.Connection, body: dict) -> dict:
    order_id = _generate_order_id()
    row = await conn.fetchrow(
        """
        INSERT INTO material_orders (
            order_id, sku, market, quantity, unit,
            order_date, expected_arrival_date,
            status, created_by, notes
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING *
        """,
        order_id,
        body["sku"], body.get("market"),
        body["quantity"], body.get("unit", "units"),
        body["order_date"], body["expected_arrival_date"],
        body.get("status", "pending"),
        body.get("created_by"), body.get("notes"),
    )
    return _row_to_dict(row)


async def get_order(conn: asyncpg.Connection, order_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT * FROM material_orders WHERE order_id = $1", order_id,
    )
    return _row_to_dict(row) if row else None


async def update_order(
    conn: asyncpg.Connection, order_id: str, body: dict,
) -> Optional[dict]:
    """Dynamic UPDATE. Builds a SET clause from whichever keys appear in
    `body` (with non-None values), and ALWAYS appends updated_at = NOW().
    Empty body still bumps updated_at."""
    updates: list[str] = []
    params: list[Any] = []
    for col in ("sku", "market", "quantity", "unit", "order_date",
                "expected_arrival_date", "status", "created_by", "notes"):
        if col in body and body[col] is not None:
            params.append(body[col])
            updates.append(f"{col} = ${len(params)}")
    updates.append("updated_at = NOW()")  # required: no ON UPDATE trigger
    params.append(order_id)
    sql = f"""
        UPDATE material_orders
        SET {", ".join(updates)}
        WHERE order_id = ${len(params)}
        RETURNING *
    """
    row = await conn.fetchrow(sql, *params)
    return _row_to_dict(row) if row else None


async def delete_order(conn: asyncpg.Connection, order_id: str) -> bool:
    result = await conn.execute(
        "DELETE FROM material_orders WHERE order_id = $1", order_id,
    )
    # asyncpg returns "DELETE <n>" — non-zero means a row was removed.
    return result.endswith(" 1")


async def list_orders(
    conn: asyncpg.Connection,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    status: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM material_orders WHERE 1 = 1"
    params: list[Any] = []
    if start is not None:
        params.append(start)
        sql += f" AND expected_arrival_date >= ${len(params)}"
    if end is not None:
        params.append(end)
        sql += f" AND expected_arrival_date <= ${len(params)}"
    if status is not None:
        params.append(status)
        sql += f" AND status = ${len(params)}"
    sql += " ORDER BY expected_arrival_date ASC, order_id ASC"
    rows = await conn.fetch(sql, *params)
    return [_row_to_dict(r) for r in rows]
