"""Plain-Python email templates — return (subject, html, plain) tuples.

All user-supplied fields (machine names, technician names, descriptions)
flow through `html.escape()` before landing in HTML so a maliciously-crafted
work_description can't inject markup or scripts when an email lands in
Gmail. Plain bodies use the original text — no escaping needed there.

Phase E1: `test_email` only.
Phase E2: the five real triggers — login, fleet_digest, maint_scheduled,
          maint_logged, order_placed.

All emails share the navy/teal palette and the `_wrap_html` outer card so
inboxes render them consistently.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Optional

from .config import DASHBOARD_URL

# Palette (matches the dashboard CSS so emails feel like the app)
NAVY        = "#0A1F44"
NAVY_DEEP   = "#07173A"
TEAL        = "#0E7490"
GREEN       = "#15A56C"
AMBER       = "#F59E0B"
RED         = "#DC2626"
INK         = "#0A1F44"
INK_SOFT    = "#4B5563"
INK_DIM     = "#6B7280"
GREY_BORDER = "#E5E8EE"
GREY_BG     = "#F4F6FA"


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------

def _wrap_html(inner: str, header_kicker: str = "Operations notification",
               header_color: str = NAVY) -> str:
    """Standard outer card. Inline-styled so Gmail / Outlook render it."""
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{GREY_BG};font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{INK};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{GREY_BG};padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border:1px solid {GREY_BORDER};border-radius:12px;overflow:hidden;">
        <tr><td style="background:{header_color};padding:18px 24px;color:#ffffff;">
          <div style="font-size:11px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;color:#A9B7D6;">FHH AI Optimizer</div>
          <div style="font-size:18px;font-weight:600;letter-spacing:-0.3px;margin-top:4px;">{html.escape(header_kicker)}</div>
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


def _button_html(url: str, label: str, color: str = NAVY) -> str:
    safe = html.escape(label)
    href = html.escape(url, quote=True)
    return (
        f'<a href="{href}" style="display:inline-block;background:{color};color:#ffffff;'
        f'text-decoration:none;padding:10px 18px;border-radius:8px;font-size:13px;'
        f'font-weight:600;letter-spacing:0.2px;">{safe}</a>'
    )


def _stat_table(rows: list[tuple[str, str]]) -> str:
    """Two-column key/value strip. Each row escaped — caller passes raw text."""
    cells = []
    for k, v in rows:
        cells.append(
            f'<tr>'
            f'<td style="padding:6px 12px 6px 0;font-size:11.5px;color:{INK_DIM};'
            f'font-weight:600;letter-spacing:0.4px;text-transform:uppercase;width:36%;'
            f'vertical-align:top;">{html.escape(k)}</td>'
            f'<td style="padding:6px 0;font-size:13px;color:{INK};vertical-align:top;">'
            f'{html.escape(v)}</td>'
            f'</tr>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="background:{GREY_BG};border:1px solid {GREY_BORDER};'
        'border-radius:8px;padding:6px 14px;margin:14px 0;">'
        + "".join(cells)
        + '</table>'
    )


def _fmt_dt(dt: Any) -> str:
    """Formats a datetime as 'Mon May 10 2026 · 15:30 UTC'."""
    if dt is None:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%a %b %d %Y · %H:%M UTC")
    return str(dt)


def _fmt_money(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"${n:,.0f}" if n.is_integer() else f"${n:,.2f}"


def _fmt_hours(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:g} h"


def _fmt_qty(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:,.0f}" if n.is_integer() else f"{n:,.2f}"


# ---------------------------------------------------------------------------
# 1. test_email
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
    plain = (
        "FHH AI Optimizer — Email system check\n\n"
        "Your notification system is wired up correctly.\n\n"
        "This is the test message you triggered from POST /notifications/test-email.\n\n"
        f"Dashboard: {DASHBOARD_URL}\n\n"
        "— FHH AI Optimizer (automated message, do not reply)\n"
    )
    return subject, _wrap_html(inner), plain


# ---------------------------------------------------------------------------
# 2. login_email
# ---------------------------------------------------------------------------

def login_email(
    user: dict, login_time: datetime, fleet_summary: Optional[dict] = None,
) -> tuple[str, str, str]:
    name = user.get("full_name") or user.get("email") or "Unknown user"
    safe_name = html.escape(name)
    role = user.get("role") or "—"
    email = user.get("email") or "—"
    subject = f"🟢 {name} signed in to FHH AI Optimizer"

    fleet_line = ""
    fleet_plain = ""
    if fleet_summary:
        nc = fleet_summary.get("n_critical", 0)
        nw = fleet_summary.get("n_warning", 0)
        nh = fleet_summary.get("n_healthy", 0)
        fleet_line = (
            f'<div style="margin-top:14px;font-size:12.5px;color:{INK_SOFT};">'
            f'Fleet status: '
            f'<span style="color:{RED};font-weight:600;">{nc} critical</span> · '
            f'<span style="color:{AMBER};font-weight:600;">{nw} warning</span> · '
            f'<span style="color:{GREEN};font-weight:600;">{nh} healthy</span>'
            f'</div>'
        )
        fleet_plain = f"\nFleet status: {nc} critical · {nw} warning · {nh} healthy\n"

    inner = f"""
        <div style="font-size:15px;line-height:1.5;color:{INK};margin-bottom:8px;">
          <strong style="color:{INK};">{safe_name}</strong> signed in.
        </div>
        {_stat_table([
            ("Time", _fmt_dt(login_time)),
            ("Role", role.capitalize()),
            ("Account", email),
        ])}
        {fleet_line}
        <div style="margin:18px 0 6px;">{_button_html(DASHBOARD_URL, 'View dashboard')}</div>
    """
    plain = (
        f"{name} signed in to FHH AI Optimizer.\n\n"
        f"Time:    {_fmt_dt(login_time)}\n"
        f"Role:    {role.capitalize()}\n"
        f"Account: {email}\n"
        f"{fleet_plain}\n"
        f"Dashboard: {DASHBOARD_URL}\n\n"
        "— FHH AI Optimizer (automated message, do not reply)\n"
    )
    return subject, _wrap_html(inner, header_kicker="User signed in"), plain


# ---------------------------------------------------------------------------
# 3. fleet_digest_email (notification_type=alert_critical)
# ---------------------------------------------------------------------------

def fleet_digest_email(
    critical_alerts: list[dict], warning_alerts: list[dict],
) -> tuple[str, str, str]:
    nc = len(critical_alerts)
    nw = len(warning_alerts)

    if nc > 0:
        header_color = RED
        header_kicker = f"{nc} critical · {nw} warning"
        banner_emoji = "🚨"
    elif nw > 0:
        header_color = AMBER
        header_kicker = f"{nw} warning"
        banner_emoji = "⚠️"
    else:
        header_color = GREEN
        header_kicker = "All systems healthy"
        banner_emoji = "✅"

    subject = f"{banner_emoji} Fleet Health Report — {nc} CRITICAL · {nw} warning"

    def _alert_row(a: dict, severity_color: str, compact: bool) -> str:
        machine = html.escape(str(a.get("machine_name") or a.get("machine_id") or "?"))
        comp = html.escape(str(a.get("component_name") or a.get("component_id") or ""))
        desc = html.escape(str(a.get("description") or ""))
        score = a.get("risk_score")
        hours = a.get("predicted_failure_hours")
        sensor = a.get("top_sensor_name")
        sensor_pct = a.get("top_sensor_contribution_percent")

        comp_chip = (
            f'<span style="background:{GREY_BG};padding:1px 7px;border-radius:4px;'
            f'font-size:11px;color:{INK_DIM};margin-left:6px;">{comp}</span>'
        ) if comp else ""

        if compact:
            score_str = f' · score {int(score)}' if score is not None else ''
            return (
                f'<div style="padding:6px 0;border-bottom:1px solid {GREY_BORDER};'
                f'font-size:12.5px;color:{INK};">'
                f'<strong>{machine}</strong>{comp_chip}{score_str}'
                f'<div style="font-size:11.5px;color:{INK_DIM};margin-top:2px;">{desc}</div>'
                f'</div>'
            )

        # full row for criticals
        score_html = (
            f'<span style="font-size:18px;font-weight:700;color:{severity_color};">'
            f'{int(score)}</span>'
            f'<span style="font-size:11px;color:{INK_DIM};margin-left:4px;">/100</span>'
        ) if score is not None else ''
        hours_html = (
            f'<span style="font-size:12px;color:{INK_SOFT};">'
            f'predicted failure in {int(hours)} h</span>'
        ) if hours is not None else ''
        sensor_html = (
            f'<div style="font-size:11.5px;color:{INK_DIM};margin-top:4px;">'
            f'Top sensor: <code style="font-size:11px;color:{TEAL};">'
            f'{html.escape(str(sensor))}</code>'
            + (f' ({int(sensor_pct)}%)' if sensor_pct is not None else '')
            + '</div>'
        ) if sensor else ''
        return (
            f'<div style="padding:10px 12px;border:1px solid {GREY_BORDER};'
            f'border-left:4px solid {severity_color};border-radius:6px;'
            f'margin:8px 0;background:#ffffff;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div style="font-size:13px;font-weight:600;color:{INK};">{machine}{comp_chip}</div>'
            f'<div style="text-align:right;">{score_html}</div>'
            f'</div>'
            f'<div style="font-size:12px;color:{INK_SOFT};margin-top:4px;">{desc}</div>'
            f'<div style="margin-top:6px;">{hours_html}</div>'
            f'{sensor_html}'
            f'</div>'
        )

    crit_html = ""
    if nc > 0:
        crit_html = (
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:{RED};margin:6px 0 4px;">Critical alerts</div>'
            + "".join(_alert_row(a, RED, compact=False) for a in critical_alerts)
        )

    warn_html = ""
    if nw > 0:
        warn_html = (
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:{AMBER};margin:14px 0 4px;">Warning alerts</div>'
            + "".join(_alert_row(a, AMBER, compact=True) for a in warning_alerts)
        )

    if nc == 0 and nw == 0:
        body_html = (
            f'<div style="font-size:14px;color:{INK};line-height:1.5;">'
            f'No active alerts on the fleet right now. ✅</div>'
        )
    else:
        body_html = crit_html + warn_html

    inner = f"""
        <div style="font-size:13px;color:{INK_SOFT};margin-bottom:8px;line-height:1.5;">
          Snapshot of currently-active alerts at sign-in.
        </div>
        {body_html}
        <div style="margin:18px 0 6px;">{_button_html(DASHBOARD_URL, 'Open dashboard')}</div>
    """

    # Plain text
    lines = [f"Fleet Health Report — {nc} CRITICAL · {nw} warning", ""]
    if nc > 0:
        lines.append("CRITICAL ALERTS:")
        for a in critical_alerts:
            machine = a.get("machine_name") or a.get("machine_id") or "?"
            comp = a.get("component_name") or a.get("component_id") or ""
            desc = a.get("description") or ""
            score = a.get("risk_score")
            tail = f" — score {int(score)}/100" if score is not None else ""
            comp_part = f" {comp}" if comp else ""
            lines.append(f"  • {machine}{comp_part}{tail}")
            lines.append(f"      {desc}")
        lines.append("")
    if nw > 0:
        lines.append("WARNING ALERTS:")
        for a in warning_alerts:
            machine = a.get("machine_name") or a.get("machine_id") or "?"
            comp = a.get("component_name") or a.get("component_id") or ""
            desc = a.get("description") or ""
            comp_part = f" {comp}" if comp else ""
            lines.append(f"  • {machine}{comp_part}: {desc}")
        lines.append("")
    if nc == 0 and nw == 0:
        lines.append("No active alerts on the fleet right now.")
        lines.append("")
    lines.append(f"Dashboard: {DASHBOARD_URL}")
    lines.append("")
    lines.append("— FHH AI Optimizer (automated message, do not reply)")
    plain = "\n".join(lines)

    return subject, _wrap_html(inner, header_kicker=header_kicker, header_color=header_color), plain


# ---------------------------------------------------------------------------
# 4. maintenance_scheduled_email
# ---------------------------------------------------------------------------

def maintenance_scheduled_email(scheduled: dict) -> tuple[str, str, str]:
    machine = scheduled.get("machine_name") or scheduled.get("machine_id") or "?"
    comp = scheduled.get("component_name") or scheduled.get("component_id") or ""
    subject = f"📅 Maintenance scheduled — {machine}"
    if comp:
        subject = f"📅 Maintenance scheduled — {machine} {comp}"

    rows = [("Machine", machine)]
    if comp:
        rows.append(("Component", comp))
    if scheduled.get("action_type"):
        rows.append(("Action", str(scheduled["action_type"]).capitalize()))
    if scheduled.get("scheduled_for"):
        rows.append(("Scheduled for", _fmt_dt(scheduled["scheduled_for"])))
    if scheduled.get("technician"):
        rows.append(("Technician", str(scheduled["technician"])))
    if scheduled.get("priority"):
        rows.append(("Priority", str(scheduled["priority"]).capitalize()))
    if scheduled.get("duration_hours") is not None:
        rows.append(("Estimated duration", _fmt_hours(scheduled["duration_hours"])))
    if scheduled.get("cost_usd") is not None:
        rows.append(("Cost estimate", _fmt_money(scheduled["cost_usd"])))
    if scheduled.get("scheduled_by_user_email"):
        rows.append(("Scheduled by", str(scheduled["scheduled_by_user_email"])))

    notes = scheduled.get("work_description") or scheduled.get("notes")
    notes_html = ""
    if notes:
        notes_html = (
            f'<div style="margin-top:14px;">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:{INK_DIM};margin-bottom:6px;">Notes</div>'
            f'<div style="background:{GREY_BG};border-radius:6px;padding:10px 12px;'
            f'font-size:12.5px;color:{INK};line-height:1.55;white-space:pre-wrap;">'
            f'{html.escape(str(notes))}</div></div>'
        )

    inner = f"""
        <div style="font-size:14px;color:{INK};line-height:1.5;margin-bottom:6px;">
          A maintenance window has been scheduled.
        </div>
        {_stat_table(rows)}
        {notes_html}
        <div style="margin:18px 0 6px;">
          {_button_html(f"{DASHBOARD_URL}/?tab=calendar", 'View calendar')}
        </div>
    """

    plain_lines = [f"Maintenance scheduled — {machine}" + (f" {comp}" if comp else ""), ""]
    for k, v in rows:
        plain_lines.append(f"{k}: {v}")
    if notes:
        plain_lines.append("")
        plain_lines.append("Notes:")
        plain_lines.append(str(notes))
    plain_lines.append("")
    plain_lines.append(f"Calendar: {DASHBOARD_URL}/?tab=calendar")
    plain_lines.append("")
    plain_lines.append("— FHH AI Optimizer (automated message, do not reply)")
    plain = "\n".join(plain_lines)

    return subject, _wrap_html(inner, header_kicker="Maintenance scheduled", header_color=AMBER), plain


# ---------------------------------------------------------------------------
# 5. maintenance_logged_email
# ---------------------------------------------------------------------------

def maintenance_logged_email(entry: dict) -> tuple[str, str, str]:
    machine = entry.get("machine_name") or entry.get("machine_id") or "?"
    comp = entry.get("component_name") or entry.get("component_id") or ""
    mtype = entry.get("maintenance_type") or "maintenance"
    technician = entry.get("technician_name") or "—"
    subject = f"📝 Maintenance logged — {machine} ({mtype})"

    summary_html = (
        f'<div style="font-size:14px;color:{INK};line-height:1.55;margin-bottom:4px;">'
        f'<strong>{html.escape(technician)}</strong> logged a '
        f'<strong>{html.escape(mtype)}</strong> on '
        f'<strong>{html.escape(machine)}</strong>'
        f'{(" (" + html.escape(comp) + ")") if comp else ""}.'
        f'</div>'
    )

    rows = []
    if entry.get("performed_at"):
        rows.append(("Performed at", _fmt_dt(entry["performed_at"])))
    rows.append(("Technician", technician))
    if comp:
        rows.append(("Component", comp))
    if entry.get("cost_usd") is not None:
        rows.append(("Cost", _fmt_money(entry["cost_usd"])))
    if entry.get("duration_hours") is not None:
        rows.append(("Duration", _fmt_hours(entry["duration_hours"])))
    if entry.get("logged_by_user_email"):
        rows.append(("Logged by", str(entry["logged_by_user_email"])))

    desc = entry.get("work_description")
    desc_html = ""
    if desc:
        desc_html = (
            f'<div style="margin-top:14px;">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:{INK_DIM};margin-bottom:6px;">Work description</div>'
            f'<div style="background:{GREY_BG};border-radius:6px;padding:10px 12px;'
            f'font-size:12.5px;color:{INK};line-height:1.55;white-space:pre-wrap;">'
            f'{html.escape(str(desc))}</div></div>'
        )

    inner = f"""
        {summary_html}
        {_stat_table(rows)}
        {desc_html}
        <div style="margin:18px 0 6px;">
          {_button_html(f"{DASHBOARD_URL}/?tab=calendar", 'View calendar')}
        </div>
    """

    plain_lines = [f"Maintenance logged — {machine} ({mtype})", ""]
    plain_lines.append(f"{technician} logged a {mtype} on {machine}" + (f" ({comp})" if comp else "") + ".")
    plain_lines.append("")
    for k, v in rows:
        plain_lines.append(f"{k}: {v}")
    if desc:
        plain_lines.append("")
        plain_lines.append("Work description:")
        plain_lines.append(str(desc))
    plain_lines.append("")
    plain_lines.append(f"Calendar: {DASHBOARD_URL}/?tab=calendar")
    plain_lines.append("")
    plain_lines.append("— FHH AI Optimizer (automated message, do not reply)")
    plain = "\n".join(plain_lines)

    return subject, _wrap_html(inner, header_kicker="Maintenance entry logged", header_color=TEAL), plain


# ---------------------------------------------------------------------------
# 6. order_placed_email
# ---------------------------------------------------------------------------

def order_placed_email(order: dict) -> tuple[str, str, str]:
    sku = order.get("sku") or "?"
    qty = order.get("quantity")
    qty_str = _fmt_qty(qty)
    subject = f"📦 Material order placed — {sku} × {qty_str}"

    rows = [("SKU", str(sku)), ("Quantity", qty_str)]
    if order.get("unit"):
        rows.append(("Unit", str(order["unit"])))
    if order.get("market"):
        rows.append(("Market", str(order["market"]).upper()))
    if order.get("order_date"):
        rows.append(("Order date", _fmt_dt(order["order_date"])))
    if order.get("arrival_date") or order.get("expected_arrival_date"):
        rows.append(("Expected arrival",
                     _fmt_dt(order.get("arrival_date") or order["expected_arrival_date"])))
    if order.get("lead_time_days") is not None:
        rows.append(("Lead time", f"{int(order['lead_time_days'])} day(s)"))
    if order.get("ordered_by_user_email"):
        rows.append(("Ordered by", str(order["ordered_by_user_email"])))

    trigger = order.get("trigger_reason") or order.get("notes")
    trigger_html = ""
    if trigger:
        trigger_html = (
            f'<div style="margin-top:14px;">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;'
            f'text-transform:uppercase;color:{INK_DIM};margin-bottom:6px;">Context</div>'
            f'<div style="background:{GREY_BG};border-radius:6px;padding:10px 12px;'
            f'font-size:12.5px;color:{INK};line-height:1.55;white-space:pre-wrap;">'
            f'{html.escape(str(trigger))}</div></div>'
        )

    inner = f"""
        <div style="font-size:14px;color:{INK};line-height:1.5;margin-bottom:6px;">
          A new material order has been placed.
        </div>
        {_stat_table(rows)}
        {trigger_html}
        <div style="margin:18px 0 6px;">
          {_button_html(f"{DASHBOARD_URL}/?tab=calendar", 'View calendar')}
        </div>
    """

    plain_lines = [f"Material order placed — {sku} × {qty_str}", ""]
    for k, v in rows:
        plain_lines.append(f"{k}: {v}")
    if trigger:
        plain_lines.append("")
        plain_lines.append("Context:")
        plain_lines.append(str(trigger))
    plain_lines.append("")
    plain_lines.append(f"Calendar: {DASHBOARD_URL}/?tab=calendar")
    plain_lines.append("")
    plain_lines.append("— FHH AI Optimizer (automated message, do not reply)")
    plain = "\n".join(plain_lines)

    return subject, _wrap_html(inner, header_kicker="Material order placed", header_color=GREEN), plain


# ---------------------------------------------------------------------------
# Stubs kept for backward compatibility — unused after E2.
# (services.py now calls login_email / fleet_digest_email / etc directly.)
# ---------------------------------------------------------------------------

def critical_alert_email(alert: dict) -> tuple[str, str, str]:
    return fleet_digest_email([alert], [])


def warning_alert_email(alert: dict) -> tuple[str, str, str]:
    return fleet_digest_email([], [alert])
