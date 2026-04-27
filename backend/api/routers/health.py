from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from .. import __version__
from ..db import db_health

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """API + DB + TimescaleDB liveness probe."""
    db = await db_health()
    overall = "ok" if db.get("connected") and db.get("timescaledb") else "degraded"
    return {
        "status": overall,
        "api_version": __version__,
        "database": {
            "connected": db.get("connected", False),
            "version": db.get("version"),
        },
        "timescaledb": {
            "active": db.get("timescaledb", False),
            "version": db.get("timescaledb_version"),
        },
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
