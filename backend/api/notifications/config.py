"""Notification configuration — read .env once at import time.

Exposes:
  RESEND_API_KEY            str
  EMAIL_FROM                str   "Display Name <user@domain>"
  NOTIFICATION_RECIPIENTS   list[str]
  DASHBOARD_URL             str   used in 'View dashboard' links

`notifications_enabled()` returns False whenever the API key OR the recipient
list is empty — main.py logs that on startup so a misconfigured deploy is
visible immediately.

Resend's `api_key` is set lazily by `services.send_email` rather than at
import time, so the rest of the API is importable in environments without
the key (CI tests, container builds before secrets are mounted).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _split_recipients(raw: str) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


RESEND_API_KEY: str = (os.getenv("RESEND_API_KEY") or "").strip()
EMAIL_FROM: str = (os.getenv("EMAIL_FROM") or "").strip() \
    or "FHH AI Optimizer <onboarding@resend.dev>"
NOTIFICATION_RECIPIENTS: list[str] = _split_recipients(
    os.getenv("NOTIFICATION_RECIPIENTS") or ""
)
DASHBOARD_URL: str = (os.getenv("DASHBOARD_URL") or "").strip() or "http://localhost:8080"


def notifications_enabled() -> bool:
    """Both a key AND at least one recipient must be set for sends to happen."""
    return bool(RESEND_API_KEY) and len(NOTIFICATION_RECIPIENTS) >= 1


# ---------------------------------------------------------------------------
# Per-trigger ON/OFF switches
#
# Each event type has its own .env flag so dev iteration doesn't email a
# room of recipients on every login. Defaults follow noise-volume
# expectations: low-frequency manual-action triggers default ON, the
# every-login triggers default OFF.
# ---------------------------------------------------------------------------

def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


EMAIL_TRIGGER_LOGIN           = _bool_env("EMAIL_TRIGGER_LOGIN",           False)
EMAIL_TRIGGER_FLEET_DIGEST    = _bool_env("EMAIL_TRIGGER_FLEET_DIGEST",    False)
EMAIL_TRIGGER_MAINT_SCHEDULED = _bool_env("EMAIL_TRIGGER_MAINT_SCHEDULED", True)
EMAIL_TRIGGER_MAINT_LOGGED    = _bool_env("EMAIL_TRIGGER_MAINT_LOGGED",    True)
EMAIL_TRIGGER_ORDER_PLACED    = _bool_env("EMAIL_TRIGGER_ORDER_PLACED",    True)


def trigger_states() -> dict[str, bool]:
    """One source of truth for the 5 toggles. Used by `trigger_enabled` and
    by the lifespan startup banner so what's logged matches what fires."""
    return {
        "login":           EMAIL_TRIGGER_LOGIN,
        "fleet_digest":    EMAIL_TRIGGER_FLEET_DIGEST,
        "maint_scheduled": EMAIL_TRIGGER_MAINT_SCHEDULED,
        "maint_logged":    EMAIL_TRIGGER_MAINT_LOGGED,
        "order_placed":    EMAIL_TRIGGER_ORDER_PLACED,
    }


def trigger_enabled(trigger_name: str) -> bool:
    """Composite gate: notifications globally enabled AND this trigger ON.

    Call sites do `if not trigger_enabled('maint_logged'): return` rather
    than checking flags individually so a missing key in .env can't
    accidentally fire the wrong subset.
    """
    if not notifications_enabled():
        return False
    return trigger_states().get(trigger_name, False)
