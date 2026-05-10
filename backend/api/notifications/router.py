"""/notifications router — admin-only test trigger + audit log."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, Depends

from ..auth.dependencies import require_role
from ..db import get_pool
from .services import list_recent_notifications, send_email
from .templates import test_email

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_pool_dep() -> asyncpg.Pool:
    return get_pool()


@router.post("/test-email")
async def post_test_email(
    _admin: dict = Depends(require_role("admin")),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> dict:
    """Fire the test email to all configured recipients.

    Each call generates a fresh uuid4 source_id so the dedupe key never
    collides — admins can hit this endpoint as many times as they want
    while debugging without the second send getting silently skipped.
    """
    subject, html, plain = test_email()
    return await send_email(
        pool,
        notification_type="test",
        source_id=str(uuid4()),
        subject=subject,
        html=html,
        plain=plain,
    )


@router.get("/recent")
async def get_recent_notifications(
    _admin: dict = Depends(require_role("admin")),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> dict:
    rows = await list_recent_notifications(pool, limit=20)
    return {"notifications": rows}
