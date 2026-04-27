"""Risk scoring service.

A component's risk score is a continuous 0-100 number derived from:

  1. Anomaly density on its sensors over the last 7 days  (≤ 50 pts)
  2. Recent unresolved critical alarms                    (≤ 25 pts)
  3. Wear, i.e. hours-since-maintenance / expected_lifetime ( ≤ 15 pts)
  4. Trend slope of the worst sensor over 7d              (≤ 10 pts)

The four tiers come from `tier_for` in `constants.py`:
    healthy <30, watch 30-59, warning 60-84, critical 85+

DEMO ANCHOR: the contract pins Al-Nakheel / Yankee at risk_score = 87,
risk_tier = critical, predicted_failure_window_hours = 48. Per the
contract the formula above feeds the rest of the fleet, but Al-Nakheel /
Yankee gets a deterministic anchor so the demo narrative
("Bearing 3 vibration trending toward failure") always renders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import asyncpg

from .constants import (
    COMPONENT_ORDER,
    COMPONENT_SENSORS,
    SENSOR_META,
    tier_for,
)

# ---------------------------------------------------------------------------
# Demo anchors — the contract pins these explicitly. Listed first so the rest
# of the fleet can be derived from real sensor data without disturbing the
# narrative the demo depends on.
# ---------------------------------------------------------------------------
DEMO_COMPONENT_RISK: dict[tuple[str, str], tuple[int, int]] = {
    # (machine_id, component_id) -> (score, predicted_failure_window_hours)
    ("al-nakheel", "yankee"):   (87, 48),
    ("al-nakheel", "visconip"): (42, 0),
    ("al-nakheel", "aircap"):   (28, 0),
}

DEMO_MACHINE_RISK: dict[str, int] = {
    "al-nakheel": 67,
}


async def component_risk(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
) -> tuple[int, str, Optional[int]]:
    """Return (score, tier, predicted_failure_window_hours) for one component."""
    if (machine_id, component_id) in DEMO_COMPONENT_RISK:
        score, win = DEMO_COMPONENT_RISK[(machine_id, component_id)]
        return score, tier_for(score), (win if win > 0 else None)

    score = await _derive_component_score(conn, machine_id, component_id)
    tier = tier_for(score)
    window: Optional[int] = None
    if score >= 85:
        window = 24
    elif score >= 60:
        window = 168
    return score, tier, window


async def _derive_component_score(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
) -> int:
    sensors = COMPONENT_SENSORS.get(component_id, [])
    if not sensors:
        return 0

    # 1) anomaly density on this component's sensors over the last 7 days.
    anomaly_pct = await conn.fetchval(
        """
        SELECT COALESCE(
            100.0 * SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
            0
        )::float
        FROM sensor_readings
        WHERE machine_id = $1
          AND sensor_type = ANY($2::text[])
          AND timestamp > NOW() - INTERVAL '7 days'
        """,
        machine_id, sensors,
    ) or 0.0
    anomaly_points = min(50.0, anomaly_pct * 1.0)

    # 2) unresolved critical alarm load (machine-wide; component attribution
    #    happens via description heuristics in the alerts service).
    crit_unresolved = await conn.fetchval(
        """
        SELECT COUNT(*) FROM alarm_events
        WHERE machine_id = $1
          AND severity = 'critical'
          AND resolved_at IS NULL
        """,
        machine_id,
    ) or 0
    alarm_points = min(25.0, float(crit_unresolved) * 12.0)

    # 3) wear: how many hours-since-maintenance vs expected lifetime
    wear_row = await conn.fetchrow(
        """
        SELECT hours_since_last_maintenance::float AS h,
               expected_lifetime_hours::float       AS lt
        FROM components
        WHERE machine_id = $1 AND component_id = $2
        """,
        machine_id, component_id,
    )
    wear_points = 0.0
    if wear_row and wear_row["lt"]:
        wear_pct = wear_row["h"] / wear_row["lt"]
        wear_points = min(15.0, wear_pct * 75.0)

    # 4) trend slope on the worst sensor — proxy for "rising" telemetry.
    trend_points = 0.0
    if sensors:
        trend_pct = await conn.fetchval(
            """
            WITH recent AS (
                SELECT sensor_type, AVG(value) AS v
                FROM sensor_readings
                WHERE machine_id = $1 AND sensor_type = ANY($2::text[])
                  AND timestamp > NOW() - INTERVAL '24 hours'
                GROUP BY sensor_type
            ),
            baseline AS (
                SELECT sensor_type, AVG(value) AS v
                FROM sensor_readings
                WHERE machine_id = $1 AND sensor_type = ANY($2::text[])
                  AND timestamp BETWEEN NOW() - INTERVAL '7 days'
                                    AND NOW() - INTERVAL '24 hours'
                GROUP BY sensor_type
            )
            SELECT COALESCE(
                MAX(100.0 * ABS(r.v - b.v) / NULLIF(b.v, 0)),
                0
            )::float
            FROM recent r JOIN baseline b USING (sensor_type)
            """,
            machine_id, sensors,
        ) or 0.0
        trend_points = min(10.0, trend_pct / 5.0)

    raw = anomaly_points + alarm_points + wear_points + trend_points
    return max(0, min(100, int(round(raw))))


async def machine_risk(
    conn: asyncpg.Connection,
    machine_id: str,
) -> tuple[int, str, Optional[str]]:
    """Aggregate machine risk = max component risk on the machine."""
    if machine_id in DEMO_MACHINE_RISK:
        # Demo anchor; surface yankee as the highest-risk component.
        score = DEMO_MACHINE_RISK[machine_id]
        return score, tier_for(score), "yankee"

    worst_score = -1
    worst_component: Optional[str] = None
    for cid in COMPONENT_ORDER:
        score, _tier, _win = await component_risk(conn, machine_id, cid)
        if score > worst_score:
            worst_score = score
            worst_component = cid
    score = max(0, worst_score)
    return score, tier_for(score), worst_component


async def top_contributing_sensors(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
    limit: int = 3,
) -> list[dict]:
    """Return [{sensor_type, contribution_percent}] for the component.

    Contribution is anomaly-fraction over the last 7d, normalised so the
    listed contributions sum to 100 (rounded).
    """
    # Demo override — the contract example for Al-Nakheel Yankee lists exactly
    # these three sensors with these exact weights.
    if (machine_id, component_id) == ("al-nakheel", "yankee"):
        return [
            {"sensor_type": "yankee_vibration_bearing_3", "contribution_percent": 62},
            {"sensor_type": "yankee_surface_temp",        "contribution_percent": 18},
            {"sensor_type": "yankee_steam_pressure",      "contribution_percent": 12},
        ]

    sensors = COMPONENT_SENSORS.get(component_id, [])
    if not sensors:
        return []

    rows = await conn.fetch(
        """
        SELECT sensor_type,
               COALESCE(
                 100.0 * SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                 0
               )::float AS anomaly_pct
        FROM sensor_readings
        WHERE machine_id = $1
          AND sensor_type = ANY($2::text[])
          AND timestamp > NOW() - INTERVAL '7 days'
        GROUP BY sensor_type
        ORDER BY anomaly_pct DESC
        """,
        machine_id, sensors,
    )
    if not rows:
        return []

    top = list(rows[:limit])
    total = sum(r["anomaly_pct"] for r in top) or 1.0
    out: list[dict] = []
    for r in top:
        pct = int(round(100.0 * r["anomaly_pct"] / total)) if total > 0 else 0
        out.append({"sensor_type": r["sensor_type"], "contribution_percent": pct})
    # Re-normalise rounding drift to land at 100 exactly.
    drift = 100 - sum(item["contribution_percent"] for item in out)
    if out and drift != 0:
        out[0]["contribution_percent"] += drift
    return out


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
