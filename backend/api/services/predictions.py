"""Per-component failure prediction service.

The prediction list returned by GET /machines/{id}/predictions reuses the
risk score: failure_probability = score / 100, confidence is a static
proxy that scales modestly with sample size (proxied as 0.78–0.86).
"""
from __future__ import annotations

from typing import Optional

import asyncpg

from .constants import COMPONENT_ORDER, tier_for
from .risk import component_risk


_RECOMMENDED_BY_TIER = {
    "healthy": "Continue monitoring. No action required.",
    "watch":   "Schedule routine inspection during next downtime window.",
    "warning": "Schedule maintenance within 7 days; stockpile spare parts.",
    "critical": "Immediate intervention. Schedule replacement at earliest opportunity.",
}

# A handful of component-specific phrasing for the warning/critical tiers
# so the cards read naturally.
_PHRASING = {
    ("yankee",   "critical"): "Schedule bearing replacement in next planned downtime window.",
    ("yankee",   "warning"):  "Inspect Yankee bearings; trend is rising.",
    ("visconip", "warning"):  "Plan ViscoNip felt change within the week.",
    ("aircap",   "warning"):  "Check AirCap inlet temperature and burner.",
}


async def predictions_for_machine(
    conn: asyncpg.Connection,
    machine_id: str,
) -> list[dict]:
    out: list[dict] = []
    for cid in COMPONENT_ORDER:
        score, tier, window = await component_risk(conn, machine_id, cid)
        prob = round(score / 100.0, 2)
        # Confidence: scaled with score magnitude (more anomalies => more signal).
        confidence = round(0.78 + (score / 1000.0), 2)
        confidence = max(0.78, min(0.92, confidence))

        recommended = _PHRASING.get((cid, tier), _RECOMMENDED_BY_TIER[tier])

        out.append({
            "component_id": cid,
            "failure_probability": prob,
            "predicted_failure_window_hours": window,
            "confidence": confidence,
            "recommended_action": recommended,
        })
    return out
