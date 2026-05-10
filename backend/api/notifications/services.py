"""DB-backed email send + dedupe.

`send_email` is the single entry point that all notification call-sites use.
For each recipient it:

  1. Runs a UNIQUE-keyed pre-check against `email_notifications_sent`
     (notification_type, source_id, recipient) and skips if a row exists.
  2. Calls `resend.Emails.send` via `asyncio.to_thread` (the SDK is sync).
  3. Records the outcome — success row carries the Resend email id; failure
     row carries `error_message` for the audit endpoint.
  4. Treats a UNIQUE-violation race (two workers trying to send the same
     thing at the same instant) as 'already sent' so we never double-mail.

Test emails (`notification_type='test'`) are NOT deduped at the call-site:
the router generates a fresh uuid4 per request as the source_id so admins
can spam the test endpoint freely while debugging.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import asyncpg

from .config import (
    EMAIL_FROM, NOTIFICATION_RECIPIENTS, RESEND_API_KEY, notifications_enabled,
)

log = logging.getLogger("fhh.api.notifications")


def _send_via_resend_sync(
    *, recipient: str, subject: str, html: str, plain: str,
) -> dict:
    """Synchronous SDK call. Caller wraps in asyncio.to_thread. Returns
    {"id": str} on success; raises on failure (network, auth, quota)."""
    import resend  # imported lazily so a missing package only breaks sends, not imports
    resend.api_key = RESEND_API_KEY
    return resend.Emails.send({
        "from":    EMAIL_FROM,
        "to":      [recipient],
        "subject": subject,
        "html":    html,
        "text":    plain,
    })


async def _already_sent(
    pool: asyncpg.Pool, notification_type: str, source_id: str, recipient: str,
) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            """
            SELECT 1 FROM email_notifications_sent
            WHERE notification_type = $1 AND source_id = $2 AND recipient = $3
            """,
            notification_type, source_id, recipient,
        )
    return bool(row)


async def _record_outcome(
    pool: asyncpg.Pool,
    *,
    notification_type: str, source_id: str, recipient: str, subject: str,
    success: bool, resend_id: Optional[str], error_message: Optional[str],
) -> None:
    """INSERT … ON CONFLICT DO NOTHING — a parallel sender already wrote a
    row for this triple. We don't override their record."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO email_notifications_sent (
                notification_type, source_id, recipient, subject,
                success, resend_id, error_message
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (notification_type, source_id, recipient) DO NOTHING
            """,
            notification_type, source_id, recipient, subject,
            success, resend_id, error_message,
        )


async def send_email(
    pool: asyncpg.Pool,
    *,
    notification_type: str,
    source_id: str,
    subject: str,
    html: str,
    plain: str,
    recipients: Optional[list[str]] = None,
) -> dict:
    """Send `subject/html/plain` to each recipient with dedupe.

    Returns:
      {
        "sent":    [recipient_addr, ...],   # actually delivered to Resend
        "skipped": [recipient_addr, ...],   # row already in dedupe table
        "failed":  [{"recipient": ..., "error": "..."}, ...],
      }

    Never raises — every failure is captured per-recipient. The audit row
    is written regardless of outcome so the /notifications/recent endpoint
    can show what failed and why.
    """
    targets = recipients if recipients is not None else NOTIFICATION_RECIPIENTS
    if not notifications_enabled():
        return {
            "sent": [],
            "skipped": [],
            "failed": [
                {"recipient": r, "error": "notifications_disabled (RESEND_API_KEY or recipients missing)"}
                for r in targets
            ],
        }

    sent: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, Any]] = []

    for recipient in targets:
        if await _already_sent(pool, notification_type, source_id, recipient):
            skipped.append(recipient)
            continue

        try:
            resp = await asyncio.to_thread(
                _send_via_resend_sync,
                recipient=recipient, subject=subject, html=html, plain=plain,
            )
            resend_id = resp.get("id") if isinstance(resp, dict) else None
            await _record_outcome(
                pool,
                notification_type=notification_type, source_id=source_id,
                recipient=recipient, subject=subject,
                success=True, resend_id=resend_id, error_message=None,
            )
            sent.append(recipient)
            log.info(
                "email sent | type=%s source=%s to=%s resend_id=%s",
                notification_type, source_id, recipient, resend_id,
            )
        except Exception as exc:  # noqa: BLE001 — Resend SDK throws ResendError + connection errors
            err = f"{type(exc).__name__}: {exc}"[:500]
            await _record_outcome(
                pool,
                notification_type=notification_type, source_id=source_id,
                recipient=recipient, subject=subject,
                success=False, resend_id=None, error_message=err,
            )
            failed.append({"recipient": recipient, "error": err})
            log.warning(
                "email FAILED | type=%s source=%s to=%s err=%s",
                notification_type, source_id, recipient, err,
            )

    return {"sent": sent, "skipped": skipped, "failed": failed}


async def list_recent_notifications(
    pool: asyncpg.Pool, limit: int = 20,
) -> list[dict]:
    """Newest-first audit log. resend_id is intentionally excluded — we
    don't surface Resend's internal IDs in the response (they're a
    log-correlation tool, not user-facing)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, notification_type, source_id, recipient, subject,
                   sent_at, success, error_message
            FROM email_notifications_sent
            ORDER BY sent_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [
        {
            "id":                str(r["id"]),
            "notification_type": r["notification_type"],
            "source_id":         r["source_id"],
            "recipient":         r["recipient"],
            "subject":           r["subject"],
            "sent_at":           r["sent_at"],
            "success":           r["success"],
            "error_message":     r["error_message"],
        }
        for r in rows
    ]
