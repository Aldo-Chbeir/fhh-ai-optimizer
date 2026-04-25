"""
FHH AI Optimizer — PostgreSQL seed data generator.

Populates every relational table with realistic FHH simulation data that
conforms to API_CONTRACT.md v1.1. All machine_id, component_id, market_id,
SKU category, and enum values are taken verbatim from the contract — no
improvisation.

Usage:
    python seed_data.py            # populate the database
    python seed_data.py --count    # dry-run; print expected counts only
    python seed_data.py --truncate # wipe tables, then populate

Environment:
    DATABASE_URL   PostgreSQL DSN (default in db.py: localhost:5432/fhh_optimizer)
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

# Local import — db.py owns the engine and DSN resolution.
from db import engine

# Faker is imported lazily so --count works on a machine without it.
try:
    from faker import Faker
    fake = Faker()
    Faker.seed(42)
except Exception:  # noqa: BLE001
    fake = None

random.seed(42)

# Anchor "today" so the seeded data is reproducible and the demo narrative
# (Al Nakheel Yankee imminent failure) lines up with the contract's example
# timestamps (2026-04-25).
TODAY = date(2026, 4, 25)
HISTORY_DAYS = 180


# =============================================================================
# Constants — taken verbatim from API_CONTRACT.md
# =============================================================================

MACHINES = [
    {
        "machine_id": "al-nakheel", "name": "Al Nakheel", "location": "Abu Dhabi, UAE",
        "model": "Valmet Advantage DCT 200TS", "installation_date": date(2018, 6, 15),
        "status": "running", "current_speed_mpm": 2150, "current_oee_percent": 89.20,
    },
    {
        "machine_id": "al-bardi", "name": "Al Bardi", "location": "Egypt",
        "model": "Valmet Advantage DCT 200TS", "installation_date": date(2019, 3, 20),
        "status": "running", "current_speed_mpm": 2080, "current_oee_percent": 93.50,
    },
    {
        "machine_id": "al-sindian", "name": "Al Sindian", "location": "Egypt",
        "model": "Valmet Advantage DCT 200TS", "installation_date": date(2020, 9, 1),
        "status": "running", "current_speed_mpm": 2100, "current_oee_percent": 95.10,
    },
    {
        "machine_id": "al-snobar", "name": "Al Snobar", "location": "Jordan",
        "model": "Valmet Advantage DCT 200TS", "installation_date": date(2017, 11, 5),
        "status": "running", "current_speed_mpm": 2010, "current_oee_percent": 92.70,
    },
]

COMPONENTS_TEMPLATE = [
    {"component_id": "headbox",  "name": "OptiFlo II TIS Headbox",      "is_critical": False, "expected_lifetime_hours": 80000},
    {"component_id": "visconip", "name": "Advantage ViscoNip Press",    "is_critical": False, "expected_lifetime_hours": 60000},
    {"component_id": "yankee",   "name": "Cast Alloy Yankee Cylinder",  "is_critical": True,  "expected_lifetime_hours": 50000},
    {"component_id": "aircap",   "name": "AirCap Hood with Air System", "is_critical": False, "expected_lifetime_hours": 40000},
    {"component_id": "softreel", "name": "SoftReel Reel",               "is_critical": False, "expected_lifetime_hours": 70000},
    {"component_id": "rewinder", "name": "Focus Rewinder",              "is_critical": False, "expected_lifetime_hours": 60000},
]

SHIFTS = ("morning", "afternoon", "night")
PRODUCT_GRADES = ["Tissue 16gsm", "Tissue 18gsm", "Tissue 20gsm", "Tissue 22gsm", "Towel 24gsm"]

PRODUCTS = [
    # tissue (10)
    ("fine-facial-100",         "Fine Facial Tissue 100ct",           "tissue",     "box"),
    ("fine-facial-150",         "Fine Facial Tissue 150ct",           "tissue",     "box"),
    ("fine-facial-200",         "Fine Facial Tissue 200ct",           "tissue",     "box"),
    ("fine-facial-cube-90",     "Fine Facial Cube 90ct",              "tissue",     "box"),
    ("fine-toilet-2ply-6",      "Fine Toilet Paper 2-ply 6-roll",     "tissue",     "pack"),
    ("fine-toilet-2ply-12",     "Fine Toilet Paper 2-ply 12-roll",    "tissue",     "pack"),
    ("fine-toilet-3ply-6",      "Fine Toilet Paper 3-ply 6-roll",     "tissue",     "pack"),
    ("fine-toilet-3ply-12",     "Fine Toilet Paper 3-ply 12-roll",    "tissue",     "pack"),
    ("fine-kitchen-2roll",      "Fine Kitchen Towel 2-roll",          "tissue",     "pack"),
    ("fine-kitchen-4roll",      "Fine Kitchen Towel 4-roll",          "tissue",     "pack"),
    # baby_care (7)
    ("fine-baby-s2",            "Fine Baby Diapers Size 2",           "baby_care",  "pack"),
    ("fine-baby-s3",            "Fine Baby Diapers Size 3",           "baby_care",  "pack"),
    ("fine-baby-s4",            "Fine Baby Diapers Size 4",           "baby_care",  "pack"),
    ("fine-baby-s5",            "Fine Baby Diapers Size 5",           "baby_care",  "pack"),
    ("fine-baby-s6",            "Fine Baby Diapers Size 6",           "baby_care",  "pack"),
    ("fine-baby-wipes-64",      "Fine Baby Wipes 64ct",               "baby_care",  "pack"),
    ("fine-baby-wipes-100",     "Fine Baby Wipes 100ct",              "baby_care",  "pack"),
    # adult_care (6)
    ("fine-adult-diaper-m",     "Fine Care Adult Diapers M",          "adult_care", "pack"),
    ("fine-adult-diaper-l",     "Fine Care Adult Diapers L",          "adult_care", "pack"),
    ("fine-adult-diaper-xl",    "Fine Care Adult Diapers XL",         "adult_care", "pack"),
    ("fine-adult-underwear-m",  "Fine Care Underwear M",              "adult_care", "pack"),
    ("fine-adult-underwear-l",  "Fine Care Underwear L",              "adult_care", "pack"),
    ("fine-adult-underwear-xl", "Fine Care Underwear XL",             "adult_care", "pack"),
    # fine_guard (6)
    ("fine-guard-surgical-50",  "Fine Guard Surgical Mask 50ct",      "fine_guard", "box"),
    ("fine-guard-kn95-10",      "Fine Guard KN95 Mask 10ct",          "fine_guard", "pack"),
    ("fine-guard-n95-20",       "Fine Guard N95 Mask 20ct",           "fine_guard", "pack"),
    ("fine-guard-shield",       "Fine Guard Face Shield",             "fine_guard", "unit"),
    ("fine-guard-gloves-100",   "Fine Guard Disposable Gloves 100ct", "fine_guard", "box"),
    ("fine-guard-sani-wipes",   "Fine Guard Hand Sanitizer Wipes",    "fine_guard", "pack"),
    # wellness (4)
    ("fine-sani-50ml",          "Fine Hand Sanitizer 50ml",           "wellness",   "bottle"),
    ("fine-sani-250ml",         "Fine Hand Sanitizer 250ml",          "wellness",   "bottle"),
    ("fine-sani-500ml",         "Fine Hand Sanitizer 500ml",          "wellness",   "bottle"),
    ("fine-antibac-wipes",      "Fine Antibacterial Wet Wipes",       "wellness",   "pack"),
    # cosmetics (4)
    ("fine-beauty-tissue",      "Fine Beauty Facial Tissue Premium",  "cosmetics",  "box"),
    ("fine-cotton-pads-80",     "Fine Cotton Pads 80ct",              "cosmetics",  "pack"),
    ("fine-makeup-wipes-25",    "Fine Makeup Remover Wipes 25ct",     "cosmetics",  "pack"),
    ("fine-beauty-cleansing",   "Fine Beauty Cleansing Tissue",       "cosmetics",  "pack"),
]
assert len(PRODUCTS) == 37, f"expected 37 SKUs, got {len(PRODUCTS)}"

MARKETS = [
    ("uae",     "United Arab Emirates", "AED"),
    ("ksa",     "Saudi Arabia",         "SAR"),
    ("jordan",  "Jordan",               "JOD"),
    ("egypt",   "Egypt",                "EGP"),
    ("morocco", "Morocco",              "MAD"),
]

TECHNICIANS = ["M. Khalil", "A. Saleh", "R. Mansour", "Y. Othman", "K. Habib", "N. Farouk"]

# Component-tagged alarm templates. Frequency is shaped per-machine below so
# Al Nakheel surfaces with the most criticals (Yankee bearings).
ALARM_TEMPLATES = {
    "info": [
        ("headbox",  "Stock temperature recovered to normal range"),
        ("visconip", "Felt moisture stable"),
        ("yankee",   "Steam pressure within band"),
        ("aircap",   "Inlet temperature normal"),
        ("softreel", "Reel changeover complete"),
        ("rewinder", "Speed setpoint reached"),
    ],
    "warning": [
        ("yankee",   "Yankee bearing 1 vibration above 4.5 mm/s threshold"),
        ("yankee",   "Yankee bearing 2 vibration above 4.5 mm/s threshold"),
        ("yankee",   "Yankee bearing 3 vibration above 5.0 mm/s threshold"),
        ("yankee",   "Creping blade pressure deviation"),
        ("yankee",   "Yankee surface temperature trending high"),
        ("visconip", "ViscoNip felt moisture below 35%"),
        ("visconip", "Nip pressure fluctuation detected"),
        ("aircap",   "AirCap inlet temperature drift"),
        ("aircap",   "Energy consumption above target"),
        ("headbox",  "Headbox stock temperature drift"),
        ("softreel", "SoftReel tension irregular"),
        ("rewinder", "Rewinder speed below setpoint"),
    ],
    "critical": [
        ("yankee",   "Yankee bearing 3 vibration exceeded 6.0 mm/s — predicted failure imminent"),
        ("yankee",   "Yankee surface temperature critical (>125°C)"),
        ("yankee",   "Steam pressure loss"),
        ("aircap",   "AirCap burner flameout"),
        ("visconip", "ViscoNip pressure loss — sheet break risk"),
        ("rewinder", "Rewinder emergency stop triggered"),
    ],
}

MAINT_CADENCE = {
    "yankee":   {"interval_days":  90, "type": "preventive", "name": "Yankee creping blade replacement",
                 "cost": (8000, 15000), "downtime": (4.0, 8.0)},
    "visconip": {"interval_days":  60, "type": "preventive", "name": "ViscoNip felt change",
                 "cost": (4000, 7000),  "downtime": (3.0, 6.0)},
    "aircap":   {"interval_days":  30, "type": "preventive", "name": "AirCap burner cleaning",
                 "cost": (1500, 3500),  "downtime": (2.0, 4.0)},
    "headbox":  {"interval_days": 120, "type": "preventive", "name": "Headbox screen inspection",
                 "cost": (2000, 4500),  "downtime": (2.0, 5.0)},
    "softreel": {"interval_days":  90, "type": "preventive", "name": "SoftReel bearing check",
                 "cost": (1800, 3800),  "downtime": (2.0, 4.0)},
    "rewinder": {"interval_days":  60, "type": "preventive", "name": "Rewinder blade sharpen",
                 "cost": (1200, 2800),  "downtime": (1.0, 3.0)},
}


# =============================================================================
# Generators
# =============================================================================

def _shift_window(d: date, shift: str) -> tuple[datetime, datetime]:
    if shift == "morning":
        s = datetime(d.year, d.month, d.day,  6, 0, tzinfo=timezone.utc)
        return s, s + timedelta(hours=8)
    if shift == "afternoon":
        s = datetime(d.year, d.month, d.day, 14, 0, tzinfo=timezone.utc)
        return s, s + timedelta(hours=8)
    s = datetime(d.year, d.month, d.day, 22, 0, tzinfo=timezone.utc)
    return s, s + timedelta(hours=8)


def gen_machines() -> list[dict]:
    return MACHINES


def gen_components() -> list[dict]:
    rows: list[dict] = []
    for m in MACHINES:
        is_nakheel = m["machine_id"] == "al-nakheel"
        for c in COMPONENTS_TEMPLATE:
            if is_nakheel and c["component_id"] == "yankee":
                # Pinned to surface the 87% / critical narrative.
                hours_since = 4200
                last_maint = date(2026, 1, 15)
            else:
                hours_since = random.randint(300, 2800)
                last_maint = TODAY - timedelta(days=hours_since // 24)
            rows.append({
                "component_id": c["component_id"],
                "machine_id":   m["machine_id"],
                "name":         c["name"],
                "is_critical":  c["is_critical"],
                "expected_lifetime_hours":     c["expected_lifetime_hours"],
                "hours_since_last_maintenance": hours_since,
                "last_maintenance_date":        last_maint,
            })
    return rows


def gen_production_runs() -> list[dict]:
    rows: list[dict] = []
    start_date = TODAY - timedelta(days=HISTORY_DAYS)
    for m in MACHINES:
        is_nakheel = m["machine_id"] == "al-nakheel"
        base_oee = 88.0 if is_nakheel else 93.0
        for d_offset in range(HISTORY_DAYS):
            d = start_date + timedelta(days=d_offset)
            for shift_name in SHIFTS:
                # ~3% of shifts are skipped (idle / planned downtime).
                if random.random() < 0.03:
                    continue
                start, end = _shift_window(d, shift_name)
                oee = round(random.uniform(base_oee - 8.0, base_oee + 5.0), 2)
                tons = round(random.uniform(60.0, 95.0) * (oee / 100.0), 2)
                rows.append({
                    "run_id":        f"run-{m['machine_id']}-{d.isoformat()}-{shift_name}",
                    "machine_id":    m["machine_id"],
                    "start_time":    start,
                    "end_time":      end,
                    "product_grade": random.choice(PRODUCT_GRADES),
                    "tons_produced": tons,
                    "oee_percent":   oee,
                    "shift":         shift_name,
                })
    return rows


def gen_maintenance_logs() -> list[dict]:
    rows: list[dict] = []
    start_date = TODAY - timedelta(days=HISTORY_DAYS)
    seq = 0
    for m in MACHINES:
        for comp_id, plan in MAINT_CADENCE.items():
            d = start_date + timedelta(days=random.randint(0, plan["interval_days"]))
            while d <= TODAY:
                seq += 1
                rows.append({
                    "log_id":           f"mlog-{d.isoformat()}-{seq:05d}",
                    "component_id":     comp_id,
                    "machine_id":       m["machine_id"],
                    "maintenance_type": plan["type"],
                    "date_performed":   d,
                    "cost_usd":         round(random.uniform(*plan["cost"]), 2),
                    "downtime_hours":   round(random.uniform(*plan["downtime"]), 2),
                    "technician":       random.choice(TECHNICIANS),
                    "notes":            plan["name"],
                })
                d += timedelta(days=plan["interval_days"] + random.randint(-5, 5))
        # A couple of corrective bearing replacements per machine
        for _ in range(random.randint(2, 4)):
            seq += 1
            d = start_date + timedelta(days=random.randint(0, HISTORY_DAYS))
            rows.append({
                "log_id":           f"mlog-{d.isoformat()}-{seq:05d}",
                "component_id":     "yankee",
                "machine_id":       m["machine_id"],
                "maintenance_type": "corrective",
                "date_performed":   d,
                "cost_usd":         round(random.uniform(15000, 35000), 2),
                "downtime_hours":   round(random.uniform(8.0, 18.0), 2),
                "technician":       random.choice(TECHNICIANS),
                "notes":            "Yankee bearing replacement BR-7842",
            })
    return rows


def gen_alarm_events() -> list[dict]:
    rows: list[dict] = []
    end_dt = datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=HISTORY_DAYS)
    span = int((end_dt - start_dt).total_seconds())
    seq = 0
    for m in MACHINES:
        is_nakheel = m["machine_id"] == "al-nakheel"
        n_alarms = 200 if is_nakheel else 130
        sev_weights = [55, 35, 10] if is_nakheel else [70, 27, 3]
        for _ in range(n_alarms):
            seq += 1
            severity = random.choices(["info", "warning", "critical"], weights=sev_weights)[0]
            _comp, desc = random.choice(ALARM_TEMPLATES[severity])
            ts = start_dt + timedelta(seconds=random.randint(0, span))
            resolved_at = ts + timedelta(minutes=random.randint(5, 240)) \
                if random.random() < 0.85 else None
            if severity == "critical":
                downtime = random.randint(15, 180)
            elif severity == "warning":
                downtime = random.randint(0, 30)
            else:
                downtime = 0
            rows.append({
                "alarm_id":         f"alm-{ts.strftime('%Y-%m-%d')}-{seq:05d}",
                "machine_id":       m["machine_id"],
                "timestamp":        ts,
                "severity":         severity,
                "description":      desc,
                "resolved_at":      resolved_at,
                "downtime_minutes": downtime,
            })
    # Guarantee ≥1 unresolved critical on Al Nakheel for the demo narrative.
    rows.append({
        "alarm_id":         "alm-2026-04-25-99999",
        "machine_id":       "al-nakheel",
        "timestamp":        end_dt - timedelta(hours=4),
        "severity":         "critical",
        "description":      "Yankee bearing 3 vibration exceeded 6.0 mm/s — predicted failure imminent",
        "resolved_at":      None,
        "downtime_minutes": 0,
    })
    return rows


def gen_quality_scans(production_runs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seq = 0
    for run in production_runs:
        hours = int((run["end_time"] - run["start_time"]).total_seconds() // 3600)
        for h in range(hours):
            seq += 1
            ts = run["start_time"] + timedelta(hours=h)
            rows.append({
                "scan_id":          f"qs-{seq:08d}",
                "run_id":           run["run_id"],
                "timestamp":        ts,
                "basis_weight_gsm": round(random.uniform(15.5, 22.5), 2),
                "moisture_percent": round(random.uniform( 4.0,  6.5), 2),
                "softness_index":   round(random.uniform(70.0, 92.0), 2),
                "caliper_microns":  round(random.uniform(85.0, 115.0), 2),
            })
    return rows


def gen_products() -> list[dict]:
    return [{"sku": s, "name": n, "category": c, "unit": u} for s, n, c, u in PRODUCTS]


def gen_markets() -> list[dict]:
    return [{"market_id": m, "name": n, "currency": c} for m, n, c in MARKETS]


# =============================================================================
# Insert SQL
# =============================================================================

INSERTS: dict[str, str] = {
    "machines": """
        INSERT INTO machines (machine_id, name, location, model, installation_date,
                              status, current_speed_mpm, current_oee_percent)
        VALUES (:machine_id, :name, :location, :model, :installation_date,
                :status, :current_speed_mpm, :current_oee_percent)
        ON CONFLICT (machine_id) DO NOTHING
    """,
    "components": """
        INSERT INTO components (component_id, machine_id, name, is_critical,
                                expected_lifetime_hours, hours_since_last_maintenance,
                                last_maintenance_date)
        VALUES (:component_id, :machine_id, :name, :is_critical,
                :expected_lifetime_hours, :hours_since_last_maintenance,
                :last_maintenance_date)
        ON CONFLICT DO NOTHING
    """,
    "production_runs": """
        INSERT INTO production_runs (run_id, machine_id, start_time, end_time,
                                     product_grade, tons_produced, oee_percent, shift)
        VALUES (:run_id, :machine_id, :start_time, :end_time,
                :product_grade, :tons_produced, :oee_percent, :shift)
        ON CONFLICT (run_id) DO NOTHING
    """,
    "maintenance_logs": """
        INSERT INTO maintenance_logs (log_id, component_id, machine_id, maintenance_type,
                                      date_performed, cost_usd, downtime_hours,
                                      technician, notes)
        VALUES (:log_id, :component_id, :machine_id, :maintenance_type,
                :date_performed, :cost_usd, :downtime_hours,
                :technician, :notes)
        ON CONFLICT (log_id) DO NOTHING
    """,
    "alarm_events": """
        INSERT INTO alarm_events (alarm_id, machine_id, timestamp, severity, description,
                                  resolved_at, downtime_minutes)
        VALUES (:alarm_id, :machine_id, :timestamp, :severity, :description,
                :resolved_at, :downtime_minutes)
        ON CONFLICT (alarm_id) DO NOTHING
    """,
    "quality_scans": """
        INSERT INTO quality_scans (scan_id, run_id, timestamp, basis_weight_gsm,
                                   moisture_percent, softness_index, caliper_microns)
        VALUES (:scan_id, :run_id, :timestamp, :basis_weight_gsm,
                :moisture_percent, :softness_index, :caliper_microns)
        ON CONFLICT (scan_id) DO NOTHING
    """,
    "products": """
        INSERT INTO products (sku, name, category, unit)
        VALUES (:sku, :name, :category, :unit)
        ON CONFLICT (sku) DO NOTHING
    """,
    "markets": """
        INSERT INTO markets (market_id, name, currency)
        VALUES (:market_id, :name, :currency)
        ON CONFLICT (market_id) DO NOTHING
    """,
}

TRUNCATE_SQL = """
    TRUNCATE quality_scans, alarm_events, maintenance_logs, production_runs,
             components, machines, products, markets RESTART IDENTITY CASCADE;
"""


def _bulk_insert(conn, sql: str, rows: list[dict], batch: int = 1000) -> None:
    if not rows:
        return
    stmt = text(sql)
    for i in range(0, len(rows), batch):
        conn.execute(stmt, rows[i:i + batch])


def write_to_db(payload: dict[str, list[dict]]) -> None:
    # FK-safe order
    order = ["machines", "components", "production_runs", "maintenance_logs",
             "alarm_events", "quality_scans", "products", "markets"]
    with engine.begin() as conn:
        for tbl in order:
            _bulk_insert(conn, INSERTS[tbl], payload[tbl])


def truncate_all() -> None:
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE_SQL))


# =============================================================================
# Entrypoint
# =============================================================================

def build_payload() -> dict[str, list[dict]]:
    runs = gen_production_runs()
    return {
        "machines":          gen_machines(),
        "components":        gen_components(),
        "production_runs":   runs,
        "maintenance_logs":  gen_maintenance_logs(),
        "alarm_events":      gen_alarm_events(),
        "quality_scans":     gen_quality_scans(runs),
        "products":          gen_products(),
        "markets":           gen_markets(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count",    action="store_true", help="Dry-run; print expected counts only")
    parser.add_argument("--truncate", action="store_true", help="Wipe tables before seeding")
    args = parser.parse_args()

    payload = build_payload()

    print("--- Seed record counts ---")
    total = 0
    for tbl, rows in payload.items():
        print(f"  {tbl:<18s} {len(rows):>8,d}")
        total += len(rows)
    print(f"  {'TOTAL':<18s} {total:>8,d}")

    if args.count:
        print("\n[--count] dry-run only; no DB writes performed.")
        return 0

    if args.truncate:
        print("\nTruncating tables...")
        truncate_all()

    print("\nWriting to database...")
    write_to_db(payload)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
