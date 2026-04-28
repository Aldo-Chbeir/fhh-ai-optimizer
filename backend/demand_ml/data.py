"""Data loading + Prophet-ready frame builders.

Two big jobs live here:
  1. Pull `demand_history JOIN demand_calendar` for one (market, sku) into a
     Prophet-compatible DataFrame  (`ds`, `y`, plus 5 regressor columns).
  2. Extend the calendar table forward (Ramadan/Eid 2026-2028) so the future
     dataframe has correct regressor values past the data end.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config
from backend.demand import calendar_dates as cal


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.db_url_psycopg2(), future=True, pool_pre_ping=True)
    return _engine


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------

def fetch_products() -> list[tuple[str, str]]:
    with get_engine().connect() as c:
        rows = c.execute(text("SELECT sku, category FROM products ORDER BY sku")).all()
    return [(r.sku, r.category) for r in rows]


def fetch_markets() -> list[str]:
    with get_engine().connect() as c:
        rows = c.execute(text("SELECT market_id FROM markets ORDER BY market_id")).all()
    return [r.market_id for r in rows]


def fetch_data_range() -> tuple[date, date]:
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT MIN(date) AS lo, MAX(date) AS hi FROM demand_history"
        )).one()
    return row.lo, row.hi


# ---------------------------------------------------------------------------
# Per (market, product) Prophet frame
# ---------------------------------------------------------------------------

_LOAD_SQL = """
SELECT
    d.date::date            AS ds,
    d.units_sold::float     AS y,
    COALESCE(c.is_ramadan, false)             AS is_ramadan,
    COALESCE(c.is_eid_alfitr, false)          AS is_eid_alfitr,
    COALESCE(c.is_eid_aladha, false)          AS is_eid_aladha,
    COALESCE(c.is_pre_ramadan_stockup, false) AS is_pre_ramadan_stockup,
    COALESCE(d.promo_active, false)           AS promo_active
FROM demand_history d
LEFT JOIN demand_calendar c ON c.date = d.date
WHERE d.market_id = :m AND d.product_id = :p
ORDER BY d.date
"""


def load_market_product_history(market_id: str, product_id: str) -> pd.DataFrame:
    """Return a single (market, sku) demand history frame Prophet can train on."""
    with get_engine().connect() as c:
        df = pd.read_sql(text(_LOAD_SQL), c, params={"m": market_id, "p": product_id})
    if df.empty:
        return df
    df["ds"] = pd.to_datetime(df["ds"])
    for col in config.REGRESSORS:
        df[col] = df[col].astype(int)  # Prophet wants numeric regressors
    return df


def split_train_holdout(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Time-based 80/20 split using config.TRAIN_END / HOLDOUT_START."""
    train_end = pd.Timestamp(config.TRAIN_END)
    holdout_start = pd.Timestamp(config.HOLDOUT_START)
    train = df[df["ds"] <= train_end].copy()
    holdout = df[df["ds"] >= holdout_start].copy()
    return train, holdout


# ---------------------------------------------------------------------------
# Future-frame builder — extends the calendar past the data end
# ---------------------------------------------------------------------------

def fetch_calendar_window(start: date, end: date) -> pd.DataFrame:
    """Pull the calendar between start and end (both inclusive) — used for past dates."""
    with get_engine().connect() as c:
        df = pd.read_sql(
            text("""
                SELECT date::date AS ds, is_ramadan, is_eid_alfitr, is_eid_aladha,
                       is_pre_ramadan_stockup
                FROM demand_calendar
                WHERE date BETWEEN :s AND :e
                ORDER BY date
            """),
            c, params={"s": start, "e": end},
        )
    if df.empty:
        return df
    df["ds"] = pd.to_datetime(df["ds"])
    for c_ in config.REGRESSORS:
        if c_ in df.columns:
            df[c_] = df[c_].astype(int)
    return df


def build_future_calendar(start: date, end: date) -> pd.DataFrame:
    """Synthesise a calendar frame for a forward window using the in-code
    Hijri date table. Used for the future portion of the forecast.

    Returns columns: ds, is_ramadan, is_eid_alfitr, is_eid_aladha,
    is_pre_ramadan_stockup, promo_active (always 0 for the future).
    """
    n_days = (end - start).days + 1
    days = [start + timedelta(days=i) for i in range(n_days)]

    ramadan_set: set[date] = set()
    pre_set: set[date] = set()
    fitr_set: set[date] = set()
    adha_set: set[date] = set()

    years = sorted({d.year for d in days})
    if years:
        years.append(years[-1] + 1)  # cover end-of-year pre-Ramadan stockup

    for y in years:
        for d, _ in cal.ramadan_days(y):
            ramadan_set.add(d)
        for d in cal.pre_ramadan_stockup_dates(y):
            pre_set.add(d)
        if y in cal.EID_ALFITR:
            fitr_set.add(cal.EID_ALFITR[y])
        if y in cal.EID_ALADHA:
            adha_set.add(cal.EID_ALADHA[y])

    df = pd.DataFrame({"ds": pd.to_datetime(days)})
    df["is_ramadan"] = df["ds"].dt.date.isin(ramadan_set).astype(int)
    df["is_eid_alfitr"] = df["ds"].dt.date.isin(fitr_set).astype(int)
    df["is_eid_aladha"] = df["ds"].dt.date.isin(adha_set).astype(int)
    df["is_pre_ramadan_stockup"] = df["ds"].dt.date.isin(pre_set).astype(int)
    df["promo_active"] = 0
    return df


def build_future_frame(
    last_history_date: date,
    horizon_days: int,
) -> pd.DataFrame:
    """Build the future dataframe Prophet expects (ds + regressor columns)
    for the `horizon_days` window starting the day AFTER `last_history_date`.

    The first part of the window may overlap with `demand_calendar` rows that
    were already seeded (2023-2025). For dates beyond that, we fall back to
    the in-code Hijri table.
    """
    start = last_history_date + timedelta(days=1)
    end = start + timedelta(days=horizon_days - 1)

    db_lo, db_hi = fetch_calendar_window(start, end), None
    db = db_lo  # name shadow to clean
    n_db = len(db)

    if n_db > 0 and pd.Timestamp(db["ds"].iloc[-1]).date() >= end:
        # All dates fall inside the seeded calendar window.
        db["promo_active"] = 0
        return db[["ds"] + config.REGRESSORS].copy()

    # Otherwise mix DB-known rows + computed rows for the tail
    if n_db > 0:
        last_db_date = pd.Timestamp(db["ds"].iloc[-1]).date()
        tail_start = last_db_date + timedelta(days=1)
    else:
        tail_start = start

    if tail_start <= end:
        tail = build_future_calendar(tail_start, end)
        out = pd.concat([db, tail], ignore_index=True) if n_db > 0 else tail
    else:
        out = db
    return out[["ds"] + config.REGRESSORS].copy()


# ---------------------------------------------------------------------------
# Holdout-period regressor frame (for inference re-walk)
# ---------------------------------------------------------------------------

def build_history_regressor_frame(start: date, end: date) -> pd.DataFrame:
    """Returns the regressor columns for an arbitrary historical window."""
    return fetch_calendar_window(start, end).assign(promo_active=0)
