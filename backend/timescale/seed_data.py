"""
FHH AI Optimizer — TimescaleDB sensor data seeder.

Populates `sensor_readings` (and adds corrective `maintenance_logs` entries
for historical failure events) so the demo has 12 months of believable
plant telemetry.

Conforms to API_CONTRACT.md v1.1: every machine_id, component_id, sensor_type,
and unit string is taken verbatim from the contract.

Volume target:
    4 machines × 14 sensor types × 5-minute cadence × 365 days
  = 4 × 14 × 288 × 365
  ≈ 5.89M rows                          ← ~6M target met

Failure events:
    25 total. ONE is Al Nakheel Yankee bearing 3 — pinned to the demo
    narrative (lead-up climbing in the last 11 days, predicted failure
    +48h from anchor "today" = 2026-04-25). The other 24 are historical
    and each gets a corrective maintenance_logs entry.

Usage:
    python seed_data.py            # populate (5–10 min on local Postgres)
    python seed_data.py --count    # dry-run; print expected row counts
    python seed_data.py --truncate # wipe sensor_readings + failure logs first
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
import psycopg2
from sqlalchemy import text

# Make backend/postgres/db.py importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "postgres"))
from db import engine, DATABASE_URL  # noqa: E402

# ============================================================================
# Anchors
# ============================================================================
TODAY = date(2026, 4, 25)
TODAY_DT = datetime(TODAY.year, TODAY.month, TODAY.day, 0, 0, tzinfo=timezone.utc)
HISTORY_DAYS = 365
STEP_MINUTES = 5  # 5-minute cadence → ~5.89M rows over 12 months

RNG = np.random.default_rng(42)

# ============================================================================
# Constants — verbatim from API_CONTRACT.md
# ============================================================================
MACHINES = ["al-nakheel", "al-bardi", "al-sindian", "al-snobar"]

# (sensor_type, component_id, unit, normal_min, normal_max, walk_scale)
# walk_scale = how big the random walk's per-step noise is, as a fraction of range
SENSORS: list[tuple[str, str, str, float, float, float]] = [
    ("yankee_surface_temp",         "yankee",   "°C",          100.0, 120.0, 0.004),
    ("yankee_steam_pressure",       "yankee",   "bar",           8.0,  10.0, 0.005),
    ("yankee_vibration_bearing_1",  "yankee",   "mm/s",          2.0,   4.0, 0.006),
    ("yankee_vibration_bearing_2",  "yankee",   "mm/s",          2.0,   4.0, 0.006),
    ("yankee_vibration_bearing_3",  "yankee",   "mm/s",          2.0,   4.0, 0.006),
    ("yankee_blade_pressure",       "yankee",   "kPa",          80.0, 120.0, 0.005),
    ("visconip_nip_pressure",       "visconip", "bar",           4.0,   6.0, 0.005),
    ("visconip_felt_moisture",      "visconip", "%",            35.0,  45.0, 0.004),
    ("aircap_inlet_temp",           "aircap",   "°C",          480.0, 520.0, 0.003),
    ("aircap_energy",               "aircap",   "kWh/ton",       1.8,   2.4, 0.005),
    ("headbox_stock_temp",          "headbox",  "°C",           45.0,  55.0, 0.003),
    ("softreel_tension",            "softreel", "N/m",         180.0, 220.0, 0.005),
    ("rewinder_speed",              "rewinder", "m/min",      1800.0, 2222.0, 0.004),
    ("qcs_softness_index",          "qcs",      "0-100 scale",  70.0,  90.0, 0.004),
]
assert len(SENSORS) == 14

# ============================================================================
# Failure events — 25 total
# ----------------------------------------------------------------------------
# direction = "high" → trend climbs toward (and through) normal_max
# direction = "low"  → trend drops toward (and through) normal_min
# is_historical=True → add a corrective maintenance_logs entry on failure_date
# ============================================================================
@dataclass
class FailureEvent:
    machine_id: str
    component_id: str
    sensor_type: str
    failure_timestamp: datetime
    lead_up_days: int
    direction: str          # "high" | "low"
    severity: float         # 1.0 = touch normal_max; 1.8 = 80% past max
    failure_mode: str
    is_historical: bool

def build_failure_events() -> list[FailureEvent]:
    events: list[FailureEvent] = []

    # ---- THE narrative event: Al Nakheel Yankee bearing 3 ------------------
    # 11-day lead-up already in progress; predicted failure +48h from TODAY.
    # No spike yet — the failure is in the future. Anchors the 87% risk score.
    events.append(FailureEvent(
        machine_id="al-nakheel", component_id="yankee",
        sensor_type="yankee_vibration_bearing_3",
        failure_timestamp=TODAY_DT + timedelta(hours=48),
        lead_up_days=13,  # 11 days visible in past + 2 days future
        direction="high", severity=1.8,
        failure_mode="Bearing 3 vibration trending toward failure (predicted)",
        is_historical=False,
    ))

    # ---- 24 historical failures, spread across machines / components -------
    # (machine, component, sensor, days_before_today, lead_up_days, direction, severity, mode)
    historical: list[tuple[str, str, str, int, int, str, float, str]] = [
        # Al Nakheel — 5
        ("al-nakheel", "visconip", "visconip_nip_pressure",      330, 16, "low",  0.55, "ViscoNip pressure loss; replaced press sleeve"),
        ("al-nakheel", "aircap",   "aircap_inlet_temp",          280, 18, "high", 1.40, "AirCap burner flameout; cleaned and re-ignited"),
        ("al-nakheel", "yankee",   "yankee_vibration_bearing_1", 210, 14, "high", 1.65, "Bearing 1 replacement (corrective)"),
        ("al-nakheel", "rewinder", "rewinder_speed",             140, 14, "low",  0.55, "Rewinder drive belt slipping; replaced"),
        ("al-nakheel", "headbox",  "headbox_stock_temp",          70, 21, "high", 1.30, "Headbox stock temperature drift; recalibrated"),

        # Al Bardi — 6
        ("al-bardi",   "yankee",   "yankee_vibration_bearing_2", 320, 18, "high", 1.70, "Bearing 2 wear; replaced bearing set BR-7842"),
        ("al-bardi",   "visconip", "visconip_felt_moisture",     265, 14, "low",  0.65, "ViscoNip felt change"),
        ("al-bardi",   "yankee",   "yankee_surface_temp",        200, 16, "high", 1.25, "Yankee steam trap fault; replaced"),
        ("al-bardi",   "aircap",   "aircap_energy",              155, 18, "high", 1.45, "AirCap blower bearing replacement"),
        ("al-bardi",   "softreel", "softreel_tension",            95, 14, "low",  0.55, "SoftReel load cell calibration"),
        ("al-bardi",   "rewinder", "rewinder_speed",              35, 14, "low",  0.60, "Rewinder e-stop reset; sensor recalibrated"),

        # Al Sindian — 6
        ("al-sindian", "yankee",   "yankee_steam_pressure",      310, 16, "low",  0.55, "Yankee steam pressure loss; valve repair"),
        ("al-sindian", "visconip", "visconip_nip_pressure",      245, 18, "high", 1.45, "ViscoNip overpressure; sleeve replacement"),
        ("al-sindian", "yankee",   "yankee_blade_pressure",      180, 14, "high", 1.40, "Creping blade replacement"),
        ("al-sindian", "aircap",   "aircap_inlet_temp",          120, 16, "low",  0.70, "AirCap inlet temp sensor drift; replaced"),
        ("al-sindian", "headbox",  "headbox_stock_temp",          80, 18, "high", 1.35, "Headbox heat exchanger fouling; cleaned"),
        ("al-sindian", "rewinder", "rewinder_speed",              20, 14, "low",  0.60, "Rewinder drive controller fault"),

        # Al Snobar — 6
        ("al-snobar",  "yankee",   "yankee_vibration_bearing_3", 300, 19, "high", 1.65, "Bearing 3 replacement (corrective)"),
        ("al-snobar",  "visconip", "visconip_felt_moisture",     240, 14, "high", 1.40, "ViscoNip felt saturation; replaced"),
        ("al-snobar",  "aircap",   "aircap_energy",              175, 18, "high", 1.40, "AirCap inefficiency; burner tuning"),
        ("al-snobar",  "softreel", "softreel_tension",           110, 16, "high", 1.40, "SoftReel tension overshoot; load cell"),
        ("al-snobar",  "yankee",   "yankee_surface_temp",         60, 14, "low",  0.75, "Yankee surface cold spot; insulation repair"),
        ("al-snobar",  "rewinder", "rewinder_speed",              40, 14, "low",  0.55, "Rewinder e-stop reset; recalibrated"),

        # 1 extra to reach 25 — recent visconip event on Al Bardi
        ("al-bardi",   "visconip", "visconip_nip_pressure",       12, 14, "high", 1.40, "ViscoNip pressure spike; sleeve inspection"),
    ]
    for (m, comp, sens, days_before, lead, direction, sev, mode) in historical:
        events.append(FailureEvent(
            machine_id=m, component_id=comp, sensor_type=sens,
            failure_timestamp=TODAY_DT - timedelta(days=days_before),
            lead_up_days=lead, direction=direction, severity=sev,
            failure_mode=mode, is_historical=True,
        ))

    assert len(events) == 25, f"expected 25 failure events, got {len(events)}"
    return events


# ============================================================================
# Series generation
# ============================================================================
def generate_series_for_stream(
    machine_id: str,
    sensor_type: str,
    component_id: str,
    unit: str,
    normal_min: float,
    normal_max: float,
    walk_scale: float,
    timestamps_np: np.ndarray,        # int64 epoch seconds
    timestamp_strs: list[str],
    failures: list[FailureEvent],
) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, anomaly_flags) for one (machine, sensor) stream."""
    n = len(timestamps_np)
    midpoint = (normal_min + normal_max) / 2.0
    width = normal_max - normal_min

    # Stream-specific RNG so each stream is independent but deterministic.
    seed = abs(hash((machine_id, sensor_type))) % (2**32)
    rng = np.random.default_rng(seed)

    # Random walk: cumulative small Gaussian, then clipped + centered
    walk = np.cumsum(rng.normal(0, width * walk_scale, n))
    walk = walk - walk.mean()
    walk = np.clip(walk, -width * 0.4, width * 0.4)
    # White noise on top
    noise = rng.normal(0, width * 0.025, n)
    # Daily cycle (subtle)
    seconds_in_day = 86400
    daily = (width * 0.04) * np.sin(2 * np.pi * (timestamps_np % seconds_in_day) / seconds_in_day)

    values = np.full(n, midpoint, dtype=float) + walk + noise + daily
    anomaly = np.zeros(n, dtype=bool)

    # Apply failure events
    for evt in failures:
        if evt.machine_id != machine_id or evt.sensor_type != sensor_type:
            continue
        fail_ts_epoch = int(evt.failure_timestamp.timestamp())
        lead_start_epoch = fail_ts_epoch - evt.lead_up_days * 86400
        in_lead = (timestamps_np >= lead_start_epoch) & (timestamps_np <= fail_ts_epoch)
        if not in_lead.any():
            continue

        # progress 0→1 across the lead-up window
        progress = (timestamps_np[in_lead] - lead_start_epoch) / float(fail_ts_epoch - lead_start_epoch)

        if evt.direction == "high":
            # target offset at failure = severity * width above midpoint
            target_off = (evt.severity - 0.5) * width  # past normal_max by some margin
            offsets = target_off * progress
        else:  # "low"
            target_off = -(0.5 + (1.0 - evt.severity)) * width
            offsets = target_off * progress

        values[in_lead] += offsets
        anomaly[in_lead] = True

        # Spike at failure moment (historical events only)
        if evt.is_historical:
            spike_window = (timestamps_np >= fail_ts_epoch - 600) & \
                           (timestamps_np <= fail_ts_epoch + 600)  # ±10 min
            if spike_window.any():
                if evt.direction == "high":
                    values[spike_window] = normal_max * (evt.severity * 1.05)
                else:
                    values[spike_window] = normal_min * (evt.severity * 0.95)
                anomaly[spike_window] = True

    return values, anomaly


# ============================================================================
# Bulk loader
# ============================================================================
def _psycopg2_conn():
    url = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def copy_stream(
    cur, machine_id: str, component_id: str, sensor_type: str, unit: str,
    timestamp_strs: list[str], values: np.ndarray, anomaly: np.ndarray,
) -> int:
    """Stream a (machine, sensor) chunk into sensor_readings via COPY."""
    buf = io.StringIO()
    # Build text-format COPY data: tab-separated, 't'/'f' for booleans
    write = buf.write
    for ts, v, a in zip(timestamp_strs, values, anomaly):
        write(ts); write("\t")
        write(machine_id); write("\t")
        write(component_id); write("\t")
        write(sensor_type); write("\t")
        write(f"{v:.4f}"); write("\t")
        write(unit); write("\t")
        write("t" if a else "f"); write("\n")
    buf.seek(0)
    cur.copy_expert(
        "COPY sensor_readings (timestamp, machine_id, component_id, sensor_type, "
        "value, unit, is_anomaly) FROM STDIN WITH (FORMAT text)",
        buf,
    )
    return len(timestamp_strs)


def insert_failure_maintenance_logs(events: list[FailureEvent]) -> int:
    """Insert a corrective maintenance_logs row for each historical failure."""
    rows = []
    for i, evt in enumerate(events):
        if not evt.is_historical:
            continue
        d = evt.failure_timestamp.date()
        rows.append({
            "log_id": f"mlog-failure-{i:03d}",
            "component_id": evt.component_id,
            "machine_id": evt.machine_id,
            "maintenance_type": "corrective",
            "date_performed": d,
            "cost_usd": 18000.0 + (i * 113) % 12000,
            "downtime_hours": 6.0 + (i * 0.7) % 8.0,
            "technician": ["M. Khalil","A. Saleh","R. Mansour","Y. Othman","K. Habib","N. Farouk"][i % 6],
            "notes": evt.failure_mode,
        })
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO maintenance_logs (log_id, component_id, machine_id, maintenance_type,
                                          date_performed, cost_usd, downtime_hours,
                                          technician, notes)
            VALUES (:log_id, :component_id, :machine_id, :maintenance_type,
                    :date_performed, :cost_usd, :downtime_hours,
                    :technician, :notes)
            ON CONFLICT (log_id, date_performed) DO NOTHING
        """), rows)
    return len(rows)


# ============================================================================
# Driver
# ============================================================================
def expected_row_count() -> int:
    n_per_stream = (HISTORY_DAYS * 24 * 60) // STEP_MINUTES
    return len(MACHINES) * len(SENSORS) * n_per_stream


def truncate_sensor_data() -> None:
    print("[truncate] Wiping sensor_readings + failure maintenance_logs...")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE sensor_readings"))
        conn.execute(text("DELETE FROM maintenance_logs WHERE log_id LIKE 'mlog-failure-%'"))


def run_seed(dry_run: bool) -> None:
    failures = build_failure_events()
    expected = expected_row_count()

    print(f"[plan]   step={STEP_MINUTES}min, history={HISTORY_DAYS}d, "
          f"machines={len(MACHINES)}, sensors={len(SENSORS)}")
    print(f"[plan]   expected sensor_readings rows ~= {expected:,}")
    print(f"[plan]   failure events: {len(failures)} "
          f"(historical={sum(1 for e in failures if e.is_historical)}, "
          f"narrative={sum(1 for e in failures if not e.is_historical)})")

    if dry_run:
        return

    # Pre-compute timestamps once (same for all streams)
    end_dt = TODAY_DT
    start_dt = end_dt - timedelta(days=HISTORY_DAYS)
    n_steps = int((end_dt - start_dt).total_seconds() // (STEP_MINUTES * 60))
    print(f"[gen]    building timestamp grid ({n_steps:,} points)...")
    t0 = time.time()
    timestamps_dt = [start_dt + timedelta(minutes=STEP_MINUTES * i) for i in range(n_steps)]
    timestamps_np = np.array([int(t.timestamp()) for t in timestamps_dt], dtype=np.int64)
    timestamp_strs = [t.strftime("%Y-%m-%d %H:%M:%S+00") for t in timestamps_dt]
    print(f"[gen]    timestamps built in {time.time()-t0:.1f}s")

    # Stream rows in via COPY, one (machine, sensor) chunk at a time
    conn = _psycopg2_conn()
    conn.autocommit = False
    cur = conn.cursor()
    total_rows = 0
    last_progress = 0
    t_start = time.time()
    try:
        for machine_id in MACHINES:
            for (sensor_type, component_id, unit, nmin, nmax, wscale) in SENSORS:
                values, anomaly = generate_series_for_stream(
                    machine_id, sensor_type, component_id, unit,
                    nmin, nmax, wscale, timestamps_np, timestamp_strs, failures,
                )
                rows = copy_stream(
                    cur, machine_id, component_id, sensor_type, unit,
                    timestamp_strs, values, anomaly,
                )
                total_rows += rows
                # Progress every ~500K rows
                if total_rows - last_progress >= 500_000:
                    elapsed = time.time() - t_start
                    rate = total_rows / max(elapsed, 0.001)
                    print(f"[copy]   {total_rows:>9,} rows "
                          f"({elapsed:6.1f}s, {rate:,.0f} rows/s)")
                    last_progress = total_rows
                    conn.commit()  # checkpoint
        conn.commit()
    finally:
        cur.close()
        conn.close()

    elapsed = time.time() - t_start
    print(f"[copy]   {total_rows:>9,} rows total in {elapsed:.1f}s "
          f"({total_rows/elapsed:,.0f} rows/s)")

    # Add corrective maintenance logs for historical failures
    n_logs = insert_failure_maintenance_logs(failures)
    print(f"[maint]  inserted {n_logs} corrective maintenance_logs entries")

    # Refresh continuous aggregate over the historical range so the AI/ETL
    # layer can immediately query the hourly rollups
    print("[cagg]   refreshing sensor_readings_hourly (this can take a minute)...")
    raw = _psycopg2_conn()
    raw.autocommit = True
    rcur = raw.cursor()
    rcur.execute("CALL refresh_continuous_aggregate('sensor_readings_hourly', NULL, NULL)")
    rcur.close()
    raw.close()
    print("[cagg]   refresh complete")

    # Save failure event manifest for downstream reference
    import json
    manifest_path = os.path.join(os.path.dirname(__file__), "failure_events.json")
    with open(manifest_path, "w") as f:
        json.dump([asdict(e) for e in failures], f, default=str, indent=2)
    print(f"[save]   wrote failure event manifest -> {manifest_path}")


def print_table_counts() -> None:
    print("\n=== Live row counts ===")
    with engine.connect() as conn:
        tables = ["machines", "components", "production_runs", "maintenance_logs",
                  "alarm_events", "quality_scans", "products", "markets",
                  "sensor_readings"]
        total = 0
        for t in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t:<22s} {n:>12,d}")
            total += int(n)
        print(f"  {'TOTAL':<22s} {total:>12,d}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count",    action="store_true", help="dry-run; print expected counts")
    p.add_argument("--truncate", action="store_true", help="wipe sensor_readings before seeding")
    args = p.parse_args()

    if args.truncate and not args.count:
        truncate_sensor_data()
    run_seed(dry_run=args.count)
    if not args.count:
        print_table_counts()
    return 0


if __name__ == "__main__":
    sys.exit(main())
