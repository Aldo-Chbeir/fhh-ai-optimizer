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
