"""asyncpg connection pool + FastAPI dependency injection.

The pool is initialised on app startup and closed on shutdown via the
FastAPI lifespan context (see `backend.api.main`). Routes obtain a
connection through the `get_conn` async-generator dependency.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, Optional

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# `db.py` from the postgres layer accepts SQLAlchemy-style URLs
# (postgresql+psycopg2://...). asyncpg only accepts the bare scheme — strip
# the driver suffix if present.
def _normalize_dsn(raw: str) -> str:
    if "+" in raw.split("://", 1)[0]:
        head, tail = raw.split("://", 1)
        head = head.split("+", 1)[0]
        return f"{head}://{tail}"
    return raw


DATABASE_URL: str = _normalize_dsn(os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres123@localhost:5433/fhh_optimizers",
))

_pool: Optional[asyncpg.Pool] = None


async def init_pool(min_size: int = 2, max_size: int = 10) -> asyncpg.Pool:
    """Initialise the global asyncpg pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() first")
    return _pool


async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency that yields a pooled connection."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


async def db_health() -> dict:
    """Used by /health. Returns status of DB + TimescaleDB extension."""
    out = {
        "connected": False,
        "timescaledb": False,
        "version": None,
        "timescaledb_version": None,
    }
    if _pool is None:
        return out
    try:
        async with _pool.acquire() as conn:
            ver = await conn.fetchval("SELECT version()")
            out["connected"] = True
            out["version"] = ver
            ts = await conn.fetchrow(
                "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
            )
            if ts:
                out["timescaledb"] = True
                out["timescaledb_version"] = ts["extversion"]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out
