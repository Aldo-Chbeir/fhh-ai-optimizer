"""Plain-Python email templates — return (subject, html, plain) tuples.

All user-supplied fields (machine names, technician names, descriptions)
flow through `html.escape()` before landing in HTML so a maliciously-crafted
work_description can't inject markup or scripts when an email lands in
Gmail. Plain bodies use the original text — no escaping needed there.

E1 only ships `test_email`. The other functions are stubs that other
phases will fill in (E2 alert emails, E3 scheduled-maintenance, E4 order,
E5 logged-maintenance). Keeping them here as stubs so /notifications/test
doesn't have to special-case template existence.
"""
from __future__ import annotations

import html
from typing import Any

from .config import DASHBOARD_URL

NAVY = "#0A1F44"
TEAL = "#0E7490"
INK = "#0A1F44"
INK_SOFT = "#4B5563"
GREY_BORDER = "#E5E8EE"
GREY_BG = "#F4F6FA"


def _wrap_html(inner: str) -> str:
    """Standard outer card. Inline-styled so Gmail / Outlook render it."""
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{GREY_BG};font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{INK};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{GREY_BG};padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border:1px solid {GREY_BORDER};border-radius:12px;overflow:hidden;">
        <tr><td style="background:{NAVY};padding:18px 24px;color:#ffffff;">
          <div style="font-size:11px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;color:#A9B7D6;">FHH AI Optimizer</div>
          <div style="font-size:18px;font-weight:600;letter-spacing:-0.3px;margin-top:4px;">Operations notification</div>
        </td></tr>
        <tr><td style="padding:24px;">
          {inner}
        </td></tr>
        <tr><td style="background:{GREY_BG};padding:14px 24px;border-top:1px solid {GREY_BORDER};font-size:11.5px;color:{INK_SOFT};">
          — FHH AI Optimizer · automated message, do not reply
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _button_html(url: str, label: str) -> str:
    safe = html.escape(label)
    href = html.escape(url, quote=True)
    return (
        f'<a href="{href}" style="display:inline-block;background:{NAVY};color:#ffffff;'
        f'text-decoration:none;padding:10px 18px;border-radius:8px;font-size:13px;'
        f'font-weight:600;letter-spacing:0.2px;">{safe}</a>'
    )


# ---------------------------------------------------------------------------
# E1 — fully implemented
# ---------------------------------------------------------------------------

def test_email() -> tuple[str, str, str]:
    subject = "FHH AI Optimizer — Email system check"
    inner = f"""
        <div style="font-size:15px;line-height:1.5;color:{INK};margin-bottom:16px;">
          🎉 Your notification system is wired up correctly.
        </div>
        <div style="font-size:13px;color:{INK_SOFT};margin-bottom:20px;line-height:1.55;">
          This is the test message you triggered from
          <code style="background:{GREY_BG};padding:1px 5px;border-radius:4px;font-size:12px;color:{TEAL};">POST /notifications/test-email</code>.
          Future alerts, scheduled maintenance, and material-order events will
          arrive in this same inbox using the same template.
        </div>
        <div style="margin:18px 0 6px;">{_button_html(DASHBOARD_URL, 'View dashboard')}</div>
    """
    html_body = _wrap_html(inner)
    plain_body = (
        "FHH AI Optimizer — Email system check\n"
        "\n"
        "Your notification system is wired up correctly.\n"
        "\n"
        "This is the test message you triggered from POST /notifications/test-email.\n"
        "Future alerts, scheduled maintenance, and material-order events will\n"
        "arrive in this same inbox using the same template.\n"
        "\n"
        f"Dashboard: {DASHBOARD_URL}\n"
        "\n"
        "— FHH AI Optimizer (automated message, do not reply)\n"
    )
    return subject, html_body, plain_body


# ---------------------------------------------------------------------------
# E2-E5 — stubs (filled in in subsequent phases)
# ---------------------------------------------------------------------------

def _stub(kind: str, payload: dict) -> tuple[str, str, str]:
    label = html.escape(kind)
    subject = f"[STUB] {kind}"
    inner = (
        f'<div style="font-size:14px;color:{INK};">[STUB] {label} template — '
        f'will be replaced in a later phase.</div>'
    )
    return subject, _wrap_html(inner), f"[STUB] {kind} template — will be replaced.\n"


def critical_alert_email(alert: dict) -> tuple[str, str, str]:
    return _stub("critical_alert", alert)


def warning_alert_email(alert: dict) -> tuple[str, str, str]:
    return _stub("warning_alert", alert)


def maintenance_scheduled_email(scheduled: dict) -> tuple[str, str, str]:
    return _stub("maintenance_scheduled", scheduled)


def maintenance_logged_email(entry: dict) -> tuple[str, str, str]:
    return _stub("maintenance_logged", entry)


def order_placed_email(order: dict) -> tuple[str, str, str]:
    return _stub("order_placed", order)
