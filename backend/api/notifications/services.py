"""DB-backed email send + dedupe + per-trigger dispatch helpers.

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

The `dispatch_*` helpers at the bottom of this file are the wrappers that
endpoint code uses. They check the per-trigger toggle, build the template
dict, generate the email, and call `send_email` — all inside a try/except
that NEVER raises into the request path. Endpoint code does:

    asyncio.create_task(dispatch_maintenance_logged(pool, entry))

…and returns to the user immediately.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import asyncpg

from . import templates
from .config import (
    EMAIL_FROM, NOTIFICATION_RECIPIENTS, RESEND_API_KEY,
    notifications_enabled, trigger_enabled,
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


# ===========================================================================
# Context helpers — read live data for digest + login emails
# ===========================================================================

async def get_fleet_alert_summary(pool: asyncpg.Pool) -> dict:
    """Cheap one-shot count for the login email. Counts active alarms by
    severity, computes 'healthy' as the complement against the 4-machine
    fleet (so it's the count of machines with no active alarm of that
    severity, not literal alarm count of 'no alarm')."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              SUM(CASE WHEN severity = 'critical' AND status='active' THEN 1 ELSE 0 END) AS n_critical,
              SUM(CASE WHEN severity = 'warning'  AND status='active' THEN 1 ELSE 0 END) AS n_warning,
              COUNT(DISTINCT machine_id) FILTER (
                WHERE severity IN ('critical','warning') AND status='active'
              ) AS n_unhealthy_machines
            FROM alarm_events
            """
        )
        total_machines = await conn.fetchval("SELECT COUNT(*) FROM machines") or 0
    nc = int(row["n_critical"] or 0)
    nw = int(row["n_warning"] or 0)
    n_unhealthy = int(row["n_unhealthy_machines"] or 0)
    return {
        "n_critical": nc,
        "n_warning":  nw,
        "n_healthy":  max(0, int(total_machines) - n_unhealthy),
    }


async def _get_active_alerts_by_severity(
    pool: asyncpg.Pool, severity: str, limit: int = 25,
) -> list[dict]:
    """Active alerts of one severity tier, joined to machines/components for
    display names. We DON'T compute risk_score / top sensor here on the
    digest path — those would require ML inference per alert (24× possible)
    and the digest fires on every login. Templates handle missing fields."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              a.alarm_id,
              a.machine_id,
              m.name        AS machine_name,
              a.severity,
              a.description,
              a.timestamp,
              a.status
            FROM alarm_events a
            LEFT JOIN machines m ON m.machine_id = a.machine_id
            WHERE a.severity = $1
              AND a.status = 'active'
            ORDER BY a.timestamp DESC
            LIMIT $2
            """,
            severity, limit,
        )
    return [
        {
            "alert_id":         ("alt-" + r["alarm_id"][4:])
                                if r["alarm_id"].startswith("alm-") else r["alarm_id"],
            "machine_id":       r["machine_id"],
            "machine_name":     r["machine_name"] or r["machine_id"],
            "component_id":     None,   # not modelled on alarm_events
            "component_name":   None,
            "severity":         r["severity"],
            "description":      r["description"],
            "risk_score":       None,
            "predicted_failure_hours": None,
            "top_sensor_name":  None,
            "top_sensor_contribution_percent": None,
        }
        for r in rows
    ]


async def get_active_critical_alerts(pool: asyncpg.Pool) -> list[dict]:
    return await _get_active_alerts_by_severity(pool, "critical")


async def get_active_warning_alerts(pool: asyncpg.Pool) -> list[dict]:
    return await _get_active_alerts_by_severity(pool, "warning")


async def get_machine_name(pool: asyncpg.Pool, machine_id: str) -> Optional[str]:
    """Lookup the display name for a machine_id — used by maint/order
    dispatchers so emails show 'Al Nakheel' rather than 'al-nakheel'."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT name FROM machines WHERE machine_id = $1", machine_id,
        )


async def get_component_name(
    pool: asyncpg.Pool, machine_id: str, component_id: Optional[str],
) -> Optional[str]:
    if not component_id:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT name FROM components WHERE machine_id = $1 AND component_id = $2",
            machine_id, component_id,
        )


# ===========================================================================
# Per-trigger dispatch helpers
#
# Each `dispatch_*` is a coroutine you fire-and-forget from the endpoint:
#     asyncio.create_task(dispatch_maintenance_logged(pool, entry))
# It checks the trigger toggle, builds the template, calls send_email, and
# swallows every exception so a Resend hiccup never blows up the user
# request. Logs go to fhh.api.notifications.
# ===========================================================================

async def _dispatch_safe(label: str, coro) -> None:
    """Execute a dispatch coroutine and log any exception. Never raises."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("email dispatch %s failed: %s: %s", label, type(exc).__name__, exc)


async def dispatch_login(
    pool: asyncpg.Pool, *, user: dict, login_time: datetime,
) -> None:
    """Fires both the login email AND (if its toggle is on) the fleet
    digest. They share the same trigger event but different toggles so an
    operator can pick 'I want login pings' OR 'I want digest only' or both."""
    if trigger_enabled("login"):
        async def _login():
            fleet_summary = await get_fleet_alert_summary(pool)
            subject, html_body, plain = templates.login_email(
                user, login_time, fleet_summary,
            )
            await send_email(
                pool, notification_type="test",  # no dedicated enum value — log under 'test'
                source_id=f"login:{user['id']}:{login_time.isoformat()}",
                subject=subject, html=html_body, plain=plain,
            )
        await _dispatch_safe("login", _login())

    if trigger_enabled("fleet_digest"):
        async def _digest():
            crit = await get_active_critical_alerts(pool)
            warn = await get_active_warning_alerts(pool)
            subject, html_body, plain = templates.fleet_digest_email(crit, warn)
            await send_email(
                pool, notification_type="alert_critical",
                source_id=f"digest:{user['id']}:{login_time.isoformat()}",
                subject=subject, html=html_body, plain=plain,
            )
        await _dispatch_safe("fleet_digest", _digest())


async def dispatch_maintenance_scheduled(
    pool: asyncpg.Pool, *, scheduled: dict,
) -> None:
    if not trigger_enabled("maint_scheduled"):
        return
    async def _do():
        # Enrich with display names if not already provided.
        if scheduled.get("machine_id") and not scheduled.get("machine_name"):
            scheduled["machine_name"] = await get_machine_name(pool, scheduled["machine_id"])
        if scheduled.get("component_id") and not scheduled.get("component_name"):
            scheduled["component_name"] = await get_component_name(
                pool, scheduled["machine_id"], scheduled["component_id"],
            )
        subject, html_body, plain = templates.maintenance_scheduled_email(scheduled)
        await send_email(
            pool, notification_type="maintenance_scheduled",
            source_id=f"sched:{scheduled.get('id') or scheduled.get('alert_id')}",
            subject=subject, html=html_body, plain=plain,
        )
    await _dispatch_safe("maint_scheduled", _do())


async def dispatch_maintenance_logged(
    pool: asyncpg.Pool, *, entry: dict,
) -> None:
    if not trigger_enabled("maint_logged"):
        return
    async def _do():
        if entry.get("machine_id") and not entry.get("machine_name"):
            entry["machine_name"] = await get_machine_name(pool, entry["machine_id"])
        if entry.get("component_id") and not entry.get("component_name"):
            entry["component_name"] = await get_component_name(
                pool, entry["machine_id"], entry["component_id"],
            )
        subject, html_body, plain = templates.maintenance_logged_email(entry)
        await send_email(
            pool, notification_type="maintenance_logged",
            source_id=f"entry:{entry['id']}",
            subject=subject, html=html_body, plain=plain,
        )
    await _dispatch_safe("maint_logged", _do())


async def dispatch_order_placed(
    pool: asyncpg.Pool, *, order: dict,
) -> None:
    if not trigger_enabled("order_placed"):
        return
    async def _do():
        subject, html_body, plain = templates.order_placed_email(order)
        await send_email(
            pool, notification_type="order_placed",
            source_id=f"order:{order.get('id') or order.get('order_id')}",
            subject=subject, html=html_body, plain=plain,
        )
    await _dispatch_safe("order_placed", _do())
