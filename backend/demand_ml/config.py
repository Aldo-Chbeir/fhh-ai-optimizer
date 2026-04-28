"""Demand-forecasting configuration: paths, hyperparameters, splits."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models" / "demand"
REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

REPORT_JSON_PATH = REPORTS_DIR / "demand_validation.json"
REPORT_MD_PATH = REPORTS_DIR / "demand_validation.md"


def model_path(market_id: str, product_id: str) -> Path:
    return MODELS_DIR / f"{market_id}_{product_id}.pkl"


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres123@localhost:5433/fhh_optimizers",
)


def db_url_psycopg2() -> str:
    if DATABASE_URL.startswith("postgresql+psycopg2"):
        return DATABASE_URL
    if DATABASE_URL.startswith("postgresql://"):
        return DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    return DATABASE_URL


# ---------------------------------------------------------------------------
# Time split — 33 months train, 3 months holdout
# ---------------------------------------------------------------------------
HISTORY_START = date(2023, 1, 1)
TRAIN_END = date(2025, 9, 30)        # inclusive
HOLDOUT_START = date(2025, 10, 1)
HOLDOUT_END = date(2025, 12, 31)     # inclusive

# ---------------------------------------------------------------------------
# Markets / SKUs (sourced from the contract; verified by data.py)
# ---------------------------------------------------------------------------
MARKETS = ["uae", "ksa", "jordan", "egypt", "morocco"]

# Boolean regressors that line up with `demand_calendar` columns.
REGRESSORS = [
    "is_ramadan",
    "is_eid_alfitr",
    "is_eid_aladha",
    "is_pre_ramadan_stockup",
    "promo_active",
]

# ---------------------------------------------------------------------------
# Prophet hyperparameters
# ---------------------------------------------------------------------------
PROPHET_PARAMS = dict(
    yearly_seasonality=True,
    weekly_seasonality=True,
    daily_seasonality=False,
    growth="linear",
    changepoint_prior_scale=0.05,
    seasonality_prior_scale=10.0,
    seasonality_mode="multiplicative",
    interval_width=0.80,    # 80 % credible interval — UI uses these as lower/upper
    uncertainty_samples=200,
)

REGRESSOR_MODE = "multiplicative"


# ---------------------------------------------------------------------------
# Forecasting defaults
# ---------------------------------------------------------------------------
DEFAULT_HORIZON_DAYS = 90
TARGET_AVG_MAPE_PCT = 12.0   # report flags an alert if the fleet average exceeds this
