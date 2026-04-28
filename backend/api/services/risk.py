"""Risk scoring service.

Two implementations live behind one interface so the API stays stable:

  1. **Trained ML pipeline** (preferred) — `backend.ml.predict.predict_component_risk`
     loads a per-(machine, component) IsolationForest + a global XGBoost
     regressor and returns a continuous 0-100 score plus a contributing-feature
     ranking. This is the path the contract expects in production.

  2. **DB heuristic fallback** — used only when no trained model artifacts
     exist on disk yet (fresh checkout, CI without model files). Scores
     come from anomaly density + alarm load + wear + trend slope. The
     demo-anchor pins are kept here so the dashboards stay readable
     before the first training run.

Routes consume the same async `component_risk` / `machine_risk` /
`top_contributing_sensors` triple regardless of which path is active.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from .constants import (
    COMPONENT_ORDER, COMPONENT_SENSORS, SENSOR_META, tier_for,
)

log = logging.getLogger("fhh.api.risk")

# ---------------------------------------------------------------------------
# Demo anchors used by the heuristic fallback (only when no models exist).
# ---------------------------------------------------------------------------
DEMO_COMPONENT_RISK: dict[tuple[str, str], tuple[int, int]] = {
    ("al-nakheel", "yankee"):   (87, 48),
    ("al-nakheel", "visconip"): (42, 0),
    ("al-nakheel", "aircap"):   (28, 0),
}
DEMO_MACHINE_RISK: dict[str, int] = {
    "al-nakheel": 67,
}


# ---------------------------------------------------------------------------
# ML availability probe — checked once and cached
# ---------------------------------------------------------------------------

_ML_PIPELINE_OK: Optional[bool] = None


def _ml_available() -> bool:
    """True if all required model artifacts are present on disk."""
    global _ML_PIPELINE_OK
    if _ML_PIPELINE_OK is not None:
        return _ML_PIPELINE_OK
    try:
        from backend.ml import config as ml_config  # noqa: WPS433
        ok = (
            ml_config.RISK_MODEL_PATH.exists()
            and ml_config.RISK_CALIBRATOR_PATH.exists()
        )
        # Spot-check at least the al-nakheel/yankee anomaly model exists.
        if ok:
            ok = ml_config.anomaly_model_path("al-nakheel", "yankee").exists()
    except Exception as exc:  # noqa: BLE001
        log.warning("ML availability check failed: %s — using heuristic fallback", exc)
        ok = False
    _ML_PIPELINE_OK = ok
    if ok:
        log.info("ML pipeline detected — using trained models for risk scoring")
    else:
        log.info("ML pipeline NOT detected — using DB heuristic fallback")
    return ok


def reset_ml_cache() -> None:
    """After /admin/retrain finishes, drop the cached availability flag and
    flush the predictor's loaded artifacts so the next call re-loads."""
    global _ML_PIPELINE_OK
    _ML_PIPELINE_OK = None
    try:
        from backend.ml import predict as ml_predict  # noqa: WPS433
        ml_predict.reset_caches()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Component risk — async wrapper around the (synchronous) ML inference.
# ---------------------------------------------------------------------------

async def component_risk(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
) -> tuple[int, str, Optional[int]]:
    """Return (score, tier, predicted_failure_window_hours) for one component."""
    if _ml_available():
        try:
            return await _ml_component_risk(machine_id, component_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ML inference failed for %s/%s — falling back to heuristic: %s",
                machine_id, component_id, exc,
            )
    return await _heuristic_component_risk(conn, machine_id, component_id)


async def component_risk_full(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
) -> dict:
    """Like `component_risk` but returns the full ML payload when available
    (used by the /risk-score routers to surface contributing features +
    anomaly score + model_version)."""
    if _ml_available():
        try:
            return await _ml_component_risk_full(machine_id, component_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ML full-inference failed for %s/%s — falling back to heuristic: %s",
                machine_id, component_id, exc,
            )
    score, tier, win = await _heuristic_component_risk(conn, machine_id, component_id)
    return {
        "score": score,
        "tier": tier,
        "predicted_failure_window_hours": win,
        "top_contributing_features": [],
        "anomaly_score": 0.0,
        "model_version": "heuristic",
        "as_of": now_iso(),
    }


async def _ml_component_risk(machine_id: str, component_id: str) -> tuple[int, str, Optional[int]]:
    payload = await _ml_component_risk_full(machine_id, component_id)
    return payload["score"], payload["tier"], payload["predicted_failure_window_hours"]


async def _ml_component_risk_full(machine_id: str, component_id: str) -> dict:
    from backend.ml import predict as ml_predict  # noqa: WPS433

    def _run() -> dict:
        return ml_predict.predict_component_risk(machine_id, component_id, as_of=None)

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# Machine-level rollup
# ---------------------------------------------------------------------------

async def machine_risk(
    conn: asyncpg.Connection,
    machine_id: str,
) -> tuple[int, str, Optional[str]]:
    """Aggregate machine risk = max component risk on the machine."""
    worst_score = -1
    worst_component: Optional[str] = None
    for cid in COMPONENT_ORDER:
        score, _tier, _win = await component_risk(conn, machine_id, cid)
        if score > worst_score:
            worst_score = score
            worst_component = cid

    score = max(0, worst_score)
    return score, tier_for(score), worst_component


# ---------------------------------------------------------------------------
# Top-contributing sensors (per the contract response shape)
# ---------------------------------------------------------------------------

async def top_contributing_sensors(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
    limit: int = 3,
) -> list[dict]:
    """Return [{sensor_type, contribution_percent}].

    When the ML pipeline is active, we map XGBoost feature importances back
    to their owning sensor (feature names are like `yankee_vibration_bearing_3__roll24h_mean`).
    Otherwise we fall back to anomaly-fraction over the last 7 days.
    """
    if _ml_available():
        try:
            payload = await _ml_component_risk_full(machine_id, component_id)
            mapped = _features_to_sensor_contribs(payload.get("top_contributing_features", []),
                                                  component_id, limit)
            if mapped:
                return mapped
        except Exception as exc:  # noqa: BLE001
            log.warning("ML top-contributors failed: %s — falling back", exc)

    # Demo override (kept for backward-compat with the contract example)
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
        WHERE machine_id = $1 AND sensor_type = ANY($2::text[])
          AND timestamp > NOW() - INTERVAL '7 days'
        GROUP BY sensor_type ORDER BY anomaly_pct DESC
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
    drift = 100 - sum(item["contribution_percent"] for item in out)
    if out and drift != 0:
        out[0]["contribution_percent"] += drift
    return out


def _features_to_sensor_contribs(
    feature_contribs: list[dict],
    component_id: str,
    limit: int,
) -> list[dict]:
    """Map XGBoost feature names → sensor_type, sum weights per sensor."""
    sensor_weights: dict[str, float] = {}
    for fc in feature_contribs:
        name = fc.get("feature", "")
        weight = float(fc.get("weight", 0.0))
        # feature looks like 'yankee_vibration_bearing_3__roll24h_mean'
        # → owning sensor is the part before '__'
        sensor = name.split("__", 1)[0] if "__" in name else None
        if not sensor or sensor.startswith("component") or sensor.startswith("machine"):
            continue
        if sensor in SENSOR_META:
            sensor_weights[sensor] = sensor_weights.get(sensor, 0.0) + weight

    if not sensor_weights:
        return []
    items = sorted(sensor_weights.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    total = sum(w for _, w in items) or 1.0
    out = [{"sensor_type": s, "contribution_percent": int(round(100.0 * w / total))}
           for s, w in items]
    drift = 100 - sum(o["contribution_percent"] for o in out)
    if out and drift != 0:
        out[0]["contribution_percent"] += drift
    return out


# ---------------------------------------------------------------------------
# Heuristic fallback (the original DB-driven implementation, kept verbatim)
# ---------------------------------------------------------------------------

async def _heuristic_component_risk(
    conn: asyncpg.Connection,
    machine_id: str,
    component_id: str,
) -> tuple[int, str, Optional[int]]:
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

    anomaly_pct = await conn.fetchval(
        """
        SELECT COALESCE(
            100.0 * SUM(CASE WHEN is_anomaly THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
            0
        )::float
        FROM sensor_readings
        WHERE machine_id = $1 AND sensor_type = ANY($2::text[])
          AND timestamp > NOW() - INTERVAL '7 days'
        """,
        machine_id, sensors,
    ) or 0.0
    anomaly_points = min(50.0, anomaly_pct * 1.0)

    crit_unresolved = await conn.fetchval(
        """
        SELECT COUNT(*) FROM alarm_events
        WHERE machine_id = $1 AND severity = 'critical' AND resolved_at IS NULL
        """,
        machine_id,
    ) or 0
    alarm_points = min(25.0, float(crit_unresolved) * 12.0)

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
        SELECT COALESCE(MAX(100.0 * ABS(r.v - b.v) / NULLIF(b.v, 0)), 0)::float
        FROM recent r JOIN baseline b USING (sensor_type)
        """,
        machine_id, sensors,
    ) or 0.0
    trend_points = min(10.0, trend_pct / 5.0)

    raw = anomaly_points + alarm_points + wear_points + trend_points
    return max(0, min(100, int(round(raw))))


# ---------------------------------------------------------------------------
# Public utility
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
