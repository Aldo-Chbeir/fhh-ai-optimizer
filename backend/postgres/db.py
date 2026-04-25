"""
FHH AI Optimizer — PostgreSQL connection + CRUD layer.

Conforms to API_CONTRACT.md v1.1. Every dict returned by a `get_*` /
`list_*` view function is shaped to drop straight into a FastAPI
JSONResponse without further mapping.

Risk score / risk tier on Machine and Component are *derived* fields in
the contract — they live in the TimescaleDB sensor model. Until that
layer lands the helpers `_derive_machine_risk` and `_derive_component_risk`
provide narrative-consistent placeholders so the demo dashboards render.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://fhh:fhh@localhost:5432/fhh_optimizer",
)

engine: Engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)

COMPONENT_ORDER: list[str] = ["headbox", "visconip", "yankee", "aircap", "softreel", "rewinder"]


# -----------------------------------------------------------------------------
# Risk derivation (placeholder; sensor-driven version lives in TimescaleDB layer)
# -----------------------------------------------------------------------------

def _tier_for(score: int) -> str:
    if score < 30:
        return "healthy"
    if score < 60:
        return "watch"
    if score < 85:
        return "warning"
    return "critical"


def _derive_machine_risk(machine_id: str, conn) -> tuple[int, str]:
    # Al Nakheel is pinned to surface the Yankee failure narrative the demo depends on.
    if machine_id == "al-nakheel":
        return 67, "warning"
    row = conn.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END), 0) AS crit,
          COALESCE(SUM(CASE WHEN severity='warning'  THEN 1 ELSE 0 END), 0) AS warn
        FROM alarm_events
        WHERE machine_id = :m
          AND timestamp > NOW() - INTERVAL '7 days'
    """), {"m": machine_id}).one()
    score = min(100, int(row.crit) * 12 + int(row.warn) * 3)
    return score, _tier_for(score)


def _derive_component_risk(machine_id: str, component_id: str) -> tuple[int, str]:
    if machine_id == "al-nakheel" and component_id == "yankee":
        return 87, "critical"
    if machine_id == "al-nakheel" and component_id == "visconip":
        return 42, "watch"
    if machine_id == "al-nakheel" and component_id == "aircap":
        return 28, "healthy"
    return 18, "healthy"


# -----------------------------------------------------------------------------
# View functions — return contract-shaped dicts
# -----------------------------------------------------------------------------

def get_machine_status(machine_id: str) -> Optional[dict[str, Any]]:
    """Return Machine object exactly as defined in API_CONTRACT.md."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT machine_id, name, location, model, installation_date, status,
                   current_speed_mpm, current_oee_percent
            FROM machines
            WHERE machine_id = :m
        """), {"m": machine_id}).mappings().first()
        if not row:
            return None
        score, tier = _derive_machine_risk(machine_id, conn)
        active = conn.execute(text("""
            SELECT COUNT(*)
            FROM alarm_events
            WHERE machine_id = :m AND resolved_at IS NULL
        """), {"m": machine_id}).scalar()
        return {
            "machine_id": row["machine_id"],
            "name": row["name"],
            "location": row["location"],
            "model": row["model"],
            "installation_date": row["installation_date"].isoformat(),
            "status": row["status"],
            "current_speed_mpm": int(row["current_speed_mpm"]),
            "current_oee_percent": float(row["current_oee_percent"]),
            "risk_score": score,
            "risk_tier": tier,
            "active_alerts_count": int(active or 0),
        }


def get_machine_components(machine_id: str) -> list[dict[str, Any]]:
    """Return the 6 components in the line order required by the contract."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT component_id, machine_id, name, is_critical, expected_lifetime_hours,
                   hours_since_last_maintenance, last_maintenance_date
            FROM components
            WHERE machine_id = :m
        """), {"m": machine_id}).mappings().all()
    by_id = {r["component_id"]: r for r in rows}
    out: list[dict[str, Any]] = []
    for cid in COMPONENT_ORDER:
        r = by_id.get(cid)
        if not r:
            continue
        score, tier = _derive_component_risk(machine_id, cid)
        out.append({
            "component_id": r["component_id"],
            "machine_id": r["machine_id"],
            "name": r["name"],
            "is_critical": bool(r["is_critical"]),
            "risk_score": score,
            "risk_tier": tier,
            "expected_lifetime_hours": int(r["expected_lifetime_hours"]),
            "hours_since_last_maintenance": int(r["hours_since_last_maintenance"]),
            "last_maintenance_date": r["last_maintenance_date"].isoformat()
                if r["last_maintenance_date"] else None,
        })
    return out


# -----------------------------------------------------------------------------
# Generic CRUD helpers
# -----------------------------------------------------------------------------

# ---- machines ---------------------------------------------------------------
def insert_machine(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO machines (machine_id, name, location, model, installation_date,
                                  status, current_speed_mpm, current_oee_percent)
            VALUES (:machine_id, :name, :location, :model, :installation_date,
                    :status, :current_speed_mpm, :current_oee_percent)
        """), row)

def get_machine(machine_id: str) -> Optional[dict]:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM machines WHERE machine_id = :m"),
                         {"m": machine_id}).mappings().first()
        return dict(r) if r else None

def list_machines() -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text("SELECT * FROM machines ORDER BY machine_id")).mappings().all()]

def update_machine_status(machine_id: str, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE machines SET status = :s WHERE machine_id = :m"),
                     {"s": status, "m": machine_id})


# ---- components -------------------------------------------------------------
def insert_component(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO components (component_id, machine_id, name, is_critical,
                                    expected_lifetime_hours, hours_since_last_maintenance,
                                    last_maintenance_date)
            VALUES (:component_id, :machine_id, :name, :is_critical,
                    :expected_lifetime_hours, :hours_since_last_maintenance,
                    :last_maintenance_date)
        """), row)

def list_components(machine_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text("SELECT * FROM components WHERE machine_id = :m"),
            {"m": machine_id}).mappings().all()]


# ---- production_runs --------------------------------------------------------
def insert_production_run(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO production_runs (run_id, machine_id, start_time, end_time,
                                         product_grade, tons_produced, oee_percent, shift)
            VALUES (:run_id, :machine_id, :start_time, :end_time,
                    :product_grade, :tons_produced, :oee_percent, :shift)
        """), row)

def list_production_runs(machine_id: str, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT * FROM production_runs WHERE machine_id = :m
            ORDER BY start_time DESC LIMIT :l
        """), {"m": machine_id, "l": limit}).mappings().all()]


# ---- maintenance_logs -------------------------------------------------------
def insert_maintenance_log(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO maintenance_logs (log_id, component_id, machine_id, maintenance_type,
                                          date_performed, cost_usd, downtime_hours,
                                          technician, notes)
            VALUES (:log_id, :component_id, :machine_id, :maintenance_type,
                    :date_performed, :cost_usd, :downtime_hours,
                    :technician, :notes)
        """), row)

def list_maintenance_logs(machine_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT * FROM maintenance_logs WHERE machine_id = :m
            ORDER BY date_performed DESC
        """), {"m": machine_id}).mappings().all()]


# ---- alarm_events -----------------------------------------------------------
def insert_alarm_event(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO alarm_events (alarm_id, machine_id, timestamp, severity,
                                      description, resolved_at, downtime_minutes)
            VALUES (:alarm_id, :machine_id, :timestamp, :severity,
                    :description, :resolved_at, :downtime_minutes)
        """), row)

def list_alarm_events(machine_id: str, severity: Optional[str] = None,
                      limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM alarm_events WHERE machine_id = :m"
    params: dict[str, Any] = {"m": machine_id, "l": limit}
    if severity:
        sql += " AND severity = :s"
        params["s"] = severity
    sql += " ORDER BY timestamp DESC LIMIT :l"
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


# ---- quality_scans ----------------------------------------------------------
def insert_quality_scan(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO quality_scans (scan_id, run_id, timestamp, basis_weight_gsm,
                                       moisture_percent, softness_index, caliper_microns)
            VALUES (:scan_id, :run_id, :timestamp, :basis_weight_gsm,
                    :moisture_percent, :softness_index, :caliper_microns)
        """), row)

def list_quality_scans(run_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text("""
            SELECT * FROM quality_scans WHERE run_id = :r ORDER BY timestamp
        """), {"r": run_id}).mappings().all()]


# ---- products ---------------------------------------------------------------
def insert_product(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO products (sku, name, category, unit)
            VALUES (:sku, :name, :category, :unit)
        """), row)

def get_product(sku: str) -> Optional[dict]:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM products WHERE sku = :s"),
                         {"s": sku}).mappings().first()
        return dict(r) if r else None

def list_products() -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text("SELECT * FROM products ORDER BY sku")).mappings().all()]


# ---- markets ----------------------------------------------------------------
def insert_market(row: dict) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO markets (market_id, name, currency)
            VALUES (:market_id, :name, :currency)
        """), row)

def list_markets() -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text("SELECT * FROM markets ORDER BY market_id")).mappings().all()]
