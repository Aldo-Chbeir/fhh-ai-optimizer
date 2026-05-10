"""DB layer for app_users — pool-first async functions.

Pool-first (vs. conn-first like services/material_orders.py) because these
helpers are also called from the auth dependency chain — see dependencies.py
— where we don't have a per-request connection in scope.

Every function `async with pool.acquire() as conn` for a single statement,
which keeps each helper independently safe to call from anywhere.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg

from .security import hash_password


def _row_to_user(r) -> dict:
    """Normalise an asyncpg row → plain dict with stringified UUID."""
    return {
        "id":            str(r["id"]),
        "email":         r["email"],
        "password_hash": r["password_hash"],
        "role":          r["role"],
        "full_name":     r["full_name"],
        "is_active":     r["is_active"],
        "created_at":    r["created_at"],
        "last_login_at": r["last_login_at"],
    }


async def get_user_by_email(pool: asyncpg.Pool, email: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM app_users WHERE email = $1", email.lower(),
        )
    return _row_to_user(row) if row else None


async def get_user_by_id(pool: asyncpg.Pool, user_id: UUID) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM app_users WHERE id = $1", user_id,
        )
    return _row_to_user(row) if row else None


async def count_users(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM app_users")
    return int(n or 0)


async def list_users(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM app_users ORDER BY created_at DESC",
        )
    return [_row_to_user(r) for r in rows]


async def create_user(
    pool: asyncpg.Pool,
    *,
    email: str,
    password: str,
    role: str,
    full_name: Optional[str] = None,
) -> dict:
    """Hash + INSERT. Caller is responsible for uniqueness check / role gating
    (see router.py) — at the DB layer we just trust args and let the unique
    constraint surface duplicate-email collisions to the caller."""
    pw_hash = hash_password(password)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO app_users (email, password_hash, role, full_name)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            email.lower(), pw_hash, role, full_name,
        )
    return _row_to_user(row)


async def touch_last_login(pool: asyncpg.Pool, user_id: UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE app_users SET last_login_at = NOW() WHERE id = $1", user_id,
        )
