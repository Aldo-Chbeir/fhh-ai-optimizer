"""ML configuration: paths, sensor metadata, hyperparameters.

The single source of truth for everything that varies between training,
evaluation, and inference.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models"
REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def anomaly_model_path(machine_id: str, component_id: str) -> Path:
    return MODELS_DIR / f"anomaly_{machine_id}_{component_id}.pkl"


RISK_MODEL_PATH = MODELS_DIR / "risk_xgb.pkl"
RISK_CALIBRATOR_PATH = MODELS_DIR / "risk_calibrator.pkl"
FEATURE_NAMES_PATH = MODELS_DIR / "feature_names.pkl"
RISK_METADATA_PATH = MODELS_DIR / "risk_metadata.pkl"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres123@localhost:5433/fhh_optimizers",
)


def db_url_psycopg2() -> str:
    """SQLAlchemy-friendly psycopg2 URL (the seeder format)."""
    if DATABASE_URL.startswith("postgresql+psycopg2"):
        return DATABASE_URL
    if DATABASE_URL.startswith("postgresql://"):
        return DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    return DATABASE_URL


# ---------------------------------------------------------------------------
# Domain constants — sensor & component metadata
# ---------------------------------------------------------------------------
MACHINES: list[str] = ["al-nakheel", "al-bardi", "al-sindian", "al-snobar"]

COMPONENT_ORDER: list[str] = [
    "headbox", "visconip", "yankee", "aircap", "softreel", "rewinder",
]

# component_id → list of sensor_types attached to it
COMPONENT_SENSORS: dict[str, list[str]] = {
    "headbox":  ["headbox_stock_temp"],
    "visconip": ["visconip_nip_pressure", "visconip_felt_moisture"],
    "yankee":   [
        "yankee_surface_temp", "yankee_steam_pressure",
        "yankee_vibration_bearing_1", "yankee_vibration_bearing_2",
        "yankee_vibration_bearing_3", "yankee_blade_pressure",
    ],
    "aircap":   ["aircap_inlet_temp", "aircap_energy"],
    "softreel": ["softreel_tension"],
    "rewinder": ["rewinder_speed"],
}

# Cross-component machine-wide signal (line quality) — included as auxiliary feature.
QCS_SENSORS: list[str] = ["qcs_softness_index"]

# sensor_type → (unit, normal_min, normal_max)
SENSOR_RANGES: dict[str, tuple[str, float, float]] = {
    "yankee_surface_temp":         ("°C",       100.0, 120.0),
    "yankee_steam_pressure":       ("bar",        8.0,  10.0),
    "yankee_vibration_bearing_1":  ("mm/s",       2.0,   4.0),
    "yankee_vibration_bearing_2":  ("mm/s",       2.0,   4.0),
    "yankee_vibration_bearing_3":  ("mm/s",       2.0,   4.0),
    "yankee_blade_pressure":       ("kPa",       80.0, 120.0),
    "visconip_nip_pressure":       ("bar",        4.0,   6.0),
    "visconip_felt_moisture":      ("%",         35.0,  45.0),
    "aircap_inlet_temp":           ("°C",       480.0, 520.0),
    "aircap_energy":               ("kWh/ton",    1.8,   2.4),
    "headbox_stock_temp":          ("°C",        45.0,  55.0),
    "softreel_tension":            ("N/m",      180.0, 220.0),
    "rewinder_speed":              ("m/min",   1800.0, 2222.0),
    "qcs_softness_index":          ("0-100",     70.0,  90.0),
}

# ---------------------------------------------------------------------------
# Time-based train / holdout split (80/20 across whatever the data spans)
# ---------------------------------------------------------------------------
# Anchor "now" so the demo narrative is reproducible — matches the seeder.
ANCHOR_NOW_ISO = "2026-04-25T00:00:00Z"

# When loading data we'll dynamically detect MIN/MAX timestamps in the DB and
# use the first 80% of the span for training. This constant just records the
# default boundary the seed produces for clarity in the validation report.
DEFAULT_HOLDOUT_FRACTION = 0.20

# ---------------------------------------------------------------------------
# Feature engineering windows
# ---------------------------------------------------------------------------
ROLLING_WINDOWS = {
    "1h":  1,
    "6h":  6,
    "24h": 24,
    "7d":  168,
}

TREND_WINDOWS = {
    "24h": 24,
    "7d":  168,
}

# Resolution at which we compute features. Sensor data is per-5-minute, but
# computing features at every reading is overkill; hourly aggregates capture
# all the useful signal at <1% the cost.
FEATURE_RESOLUTION_HOURS = 1

# Sub-sampling step for *training* timestamps — keeps the dataset small enough
# to train in <5 min without losing the signal. We keep 1 sample every 6 hours.
TRAINING_SAMPLE_EVERY_HOURS = 6

# Look-ahead horizon for the "days to next failure" target.
FAILURE_HORIZON_DAYS = 30

# ---------------------------------------------------------------------------
# Hyperparameters
# ---------------------------------------------------------------------------
ISOLATION_FOREST = {
    "n_estimators": 100,
    "contamination": 0.05,
    "max_samples": "auto",
    "random_state": 42,
    "n_jobs": -1,
}

XGBOOST = {
    "n_estimators": 200,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_lambda": 1.0,
    "reg_alpha": 0.1,
    "min_child_weight": 4,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": 42,
    "n_jobs": -1,
}

XGBOOST_FIT = {
    "early_stopping_rounds": 20,
    "verbose": False,
}

# ---------------------------------------------------------------------------
# Risk tiers — these MUST match API_CONTRACT.md v1.1 (single source of truth)
# ---------------------------------------------------------------------------
TIER_THRESHOLDS = [
    (0.0,  30.0, "healthy"),
    (30.0, 60.0, "watch"),
    (60.0, 85.0, "warning"),
    (85.0, 101.0, "critical"),
]


def tier_for(score: float) -> str:
    for lo, hi, name in TIER_THRESHOLDS:
        if lo <= score < hi:
            return name
    return "critical"
