"""FHH AI Optimizer — demand history seeder.

Populates `demand_history` and `demand_calendar` with three years of
realistic daily demand (2023-01-01 → 2025-12-31) for every (market, SKU)
combination. The next prompt (5b) trains Prophet models on this data.

Run with:
    python -m backend.demand.seed_demand            # apply schema if needed, then seed
    python -m backend.demand.seed_demand --truncate # wipe + re-seed
    python -m backend.demand.seed_demand --count    # dry-run; print expected counts only
    python -m backend.demand.seed_demand --verify   # run verification queries only

Why a single script: the demand simulation is deterministic (`random.seed(42)`
+ NumPy seeded) so a re-run reproduces the exact same numbers — the demo
narrative (Ramadan spikes, Eid dips, ~6 % YoY growth) stays stable.
"""
from __future__ import annotations

import argparse
import io
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import psycopg2
from sqlalchemy import text

# Reuse the engine the rest of the codebase already configures.
from backend.postgres.db import engine
from backend.demand import calendar_dates as cal

log = logging.getLogger("fhh.demand.seed")

# ---------------------------------------------------------------------------
# Knobs
# ---------------------------------------------------------------------------
START_DATE = date(2023, 1, 1)
END_DATE   = date(2025, 12, 31)

RNG_SEED = 42

# Per-market base scale multiplier (acts on every product's baseline).
# UAE highest per-capita; KSA highest absolute (largest population);
# Egypt high absolute & lower per-capita; Jordan / Morocco mid-tier.
MARKET_SCALE: dict[str, float] = {
    "uae":     1.00,
    "ksa":     2.40,
    "egypt":   2.10,
    "jordan":  0.55,
    "morocco": 0.95,
}

# YoY growth rates — applied multiplicatively from year_offset = (year - 2023)
MARKET_YOY_GROWTH: dict[str, float] = {
    "uae":     0.08,
    "ksa":     0.05,
    "jordan":  0.04,
    "egypt":   0.03,
    "morocco": 0.06,
}

# Per-category baseline daily units (in the UAE; multiply by MARKET_SCALE for
# other markets) and unit price in USD.
# Numbers are rough but internally consistent — they reproduce the order of
# magnitude in the contract example (UAE Facial Tissue 100ct ≈ 142k / month).
CATEGORY_PROFILES: dict[str, dict] = {
    "tissue":     {"daily_units": 4500, "price_usd": 3.20},
    "baby_care":  {"daily_units": 1200, "price_usd": 18.50},
    "adult_care": {"daily_units":  450, "price_usd": 24.00},
    "fine_guard": {"daily_units":  900, "price_usd":  6.00},
    "wellness":   {"daily_units":  700, "price_usd":  4.50},
    "cosmetics":  {"daily_units":  500, "price_usd":  4.50},
}

# Per-SKU price override (overrides the category default when present)
SKU_PRICE_OVERRIDE: dict[str, float] = {
    "fine-facial-100":         2.50,
    "fine-facial-150":         3.50,
    "fine-facial-200":         4.50,
    "fine-facial-cube-90":     3.00,
    "fine-toilet-2ply-6":      4.50,
    "fine-toilet-2ply-12":     8.00,
    "fine-toilet-3ply-6":      6.00,
    "fine-toilet-3ply-12":    11.00,
    "fine-kitchen-2roll":      3.50,
    "fine-kitchen-4roll":      6.50,
    "fine-baby-s2":           14.00,
    "fine-baby-s3":           16.00,
    "fine-baby-s4":           18.00,
    "fine-baby-s5":           20.00,
    "fine-baby-s6":           22.00,
    "fine-baby-wipes-64":      3.00,
    "fine-baby-wipes-100":     4.50,
    "fine-adult-diaper-m":    22.00,
    "fine-adult-diaper-l":    24.00,
    "fine-adult-diaper-xl":   26.00,
    "fine-adult-underwear-m": 28.00,
    "fine-adult-underwear-l": 30.00,
    "fine-adult-underwear-xl":32.00,
    "fine-guard-surgical-50":  4.50,
    "fine-guard-kn95-10":      5.00,
    "fine-guard-n95-20":      14.00,
    "fine-guard-shield":       3.50,
    "fine-guard-gloves-100":   8.00,
    "fine-guard-sani-wipes":   3.50,
    "fine-sani-50ml":          1.50,
    "fine-sani-250ml":         5.00,
    "fine-sani-500ml":         8.00,
    "fine-antibac-wipes":      3.50,
    "fine-beauty-tissue":      4.00,
    "fine-cotton-pads-80":     3.50,
    "fine-makeup-wipes-25":    4.00,
    "fine-beauty-cleansing":   3.50,
}

# How strongly Ramadan / Eid shift each category. 1.0 = baseline.
# tissue & wellness shift the most (paper goods + sanitisers spike during
# gatherings & catering volumes); adult_care and fine_guard barely respond.
CATEGORY_RAMADAN_SENS: dict[str, float] = {
    "tissue":     1.00,
    "baby_care":  0.55,
    "wellness":   0.85,
    "cosmetics":  0.40,
    "fine_guard": 0.20,
    "adult_care": 0.20,
}

# Per-market "Ramadan intensity" — UAE/KSA largest pre-stockup; Morocco mildest.
MARKET_RAMADAN_INTENSITY: dict[str, float] = {
    "uae":     1.00,
    "ksa":     1.05,
    "jordan":  0.85,
    "egypt":   0.90,
    "morocco": 0.65,
}

# Promo windows per (market, product) per year and lift sampler.
PROMO_WINDOWS_PER_YEAR = (8, 12)
PROMO_WINDOW_LENGTH = (5, 9)
PROMO_LIFT = (0.18, 0.28)

# Daily multiplicative noise σ (5 % of expected demand)
NOISE_SIGMA = 0.05

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def apply_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        for stmt in _split_sql(sql):
            if stmt.strip():
                conn.execute(text(stmt))


def _split_sql(sql: str) -> list[str]:
    """Split on `;` outside of dollar-quoted strings — sufficient for our schema."""
    out: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            out.append("\n".join(buf))
            buf = []
    if buf:
        out.append("\n".join(buf))
    return out


# ---------------------------------------------------------------------------
# Calendar generator
# ---------------------------------------------------------------------------

def generate_calendar_rows(start: date, end: date) -> list[tuple]:
    """Build (date, is_ramadan, ramadan_day, is_eid_alfitr, is_eid_aladha,
    is_pre_ramadan_stockup, holiday_name) for every day in the seed window."""
    ramadan_day_lookup: dict[date, int] = {}
    ramadan_set: set[date] = set()
    pre_stockup_set: set[date] = set()
    eid_fitr_set: set[date] = set()
    eid_adha_set: set[date] = set()
    holiday_lookup: dict[date, str] = {}

    # Need to look one extra year forward so end-of-year rows can flag
    # next-year pre-Ramadan stockup.
    years = range(start.year, end.year + 2)
    for y in years:
        for d, idx in cal.ramadan_days(y):
            ramadan_set.add(d)
            ramadan_day_lookup[d] = idx
        for d in cal.pre_ramadan_stockup_dates(y):
            pre_stockup_set.add(d)
        if y in cal.EID_ALFITR:
            eid_d = cal.EID_ALFITR[y]
            eid_fitr_set.add(eid_d)
            holiday_lookup[eid_d] = "Eid al-Fitr"
        if y in cal.EID_ALADHA:
            eid_d = cal.EID_ALADHA[y]
            eid_adha_set.add(eid_d)
            holiday_lookup[eid_d] = "Eid al-Adha"

    rows: list[tuple] = []
    cur = start
    while cur <= end:
        rday = ramadan_day_lookup.get(cur)
        rows.append((
            cur,
            cur in ramadan_set,
            rday,
            cur in eid_fitr_set,
            cur in eid_adha_set,
            cur in pre_stockup_set,
            holiday_lookup.get(cur),
        ))
        cur += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# Demand math
# ---------------------------------------------------------------------------

def _baseline_units(market_id: str, category: str) -> float:
    base = CATEGORY_PROFILES[category]["daily_units"]
    return float(base) * MARKET_SCALE[market_id]


def _price_for(sku: str, category: str) -> float:
    return float(SKU_PRICE_OVERRIDE.get(sku, CATEGORY_PROFILES[category]["price_usd"]))


def _yoy_factor(market_id: str, d: date) -> float:
    """Compounded year-over-year growth from year 0 = 2023."""
    g = MARKET_YOY_GROWTH[market_id]
    years_elapsed = (d - START_DATE).days / 365.25
    return float((1.0 + g) ** years_elapsed)


def _weekday_factor(d: date) -> float:
    """Thursday-Saturday +8 %, Monday -5 %, otherwise neutral (small jitter)."""
    wd = d.weekday()  # Mon=0 .. Sun=6
    if wd in (3, 4, 5):       # Thu, Fri, Sat
        return 1.08
    if wd == 0:               # Mon
        return 0.95
    if wd == 6:               # Sun (mid-day shoppers)
        return 1.02
    return 1.00


def _yearly_seasonality(market_id: str, d: date) -> float:
    """Summer dip in Gulf (UAE, KSA) and winter peak in Morocco/Jordan."""
    m = d.month
    is_gulf = market_id in ("uae", "ksa")
    is_north = market_id in ("morocco", "jordan")
    if is_gulf and m in (7, 8):
        return 0.85
    if is_north and m in (12, 1, 2):
        return 1.10
    if market_id == "egypt" and m in (6, 7):
        return 0.93
    return 1.00


def _ramadan_factor(category: str, market_id: str, ramadan_day: int) -> float:
    """Multiplicative Ramadan effect, day-by-day."""
    sens = CATEGORY_RAMADAN_SENS[category] * MARKET_RAMADAN_INTENSITY[market_id]
    if 1 <= ramadan_day <= 10:
        delta = 0.20  # +20 % early-Ramadan baseline
    elif 11 <= ramadan_day <= 20:
        delta = 0.00  # mid-month dip / flat
    elif 21 <= ramadan_day <= 30:
        # Eid prep ramps from +20 % at d21 to +35 % at d29
        progress = (ramadan_day - 20) / 9.0
        delta = 0.20 + 0.15 * progress
    else:
        delta = 0.0
    return 1.0 + delta * sens


def _pre_ramadan_factor(category: str, market_id: str, days_before: int) -> float:
    """Pre-Ramadan stockup curve, ramping up over the 7 days before fasting starts.

    +30 % to +45 % depending on market intensity and category.
    days_before = 1 .. 7  (1 = the day before 1 Ramadan).
    """
    sens = CATEGORY_RAMADAN_SENS[category] * MARKET_RAMADAN_INTENSITY[market_id]
    progress = (8 - days_before) / 7.0  # 0.14 (d-7) → 1.00 (d-1)
    delta = 0.30 + 0.15 * progress       # 0.32 → 0.45
    return 1.0 + delta * sens


def _eid_alfitr_factor(category: str, market_id: str, offset_days: int) -> float:
    """offset 0 = day OF Eid (closed), -1 = day before (spike), +1 = catch-up."""
    sens = CATEGORY_RAMADAN_SENS[category] * MARKET_RAMADAN_INTENSITY[market_id]
    if offset_days == -1:
        return 1.0 + 0.65 * sens   # +65 %
    if offset_days == 0:
        return 1.0 - 0.45 * (0.5 + 0.5 * sens)  # -45% scaled
    if offset_days == 1:
        return 1.0 + 0.35 * sens   # +35 % catch-up
    return 1.0


def _eid_aladha_factor(category: str, market_id: str, offset_days: int) -> float:
    sens = CATEGORY_RAMADAN_SENS[category] * MARKET_RAMADAN_INTENSITY[market_id]
    if offset_days == -1:
        return 1.0 + 0.45 * sens
    if offset_days == 0:
        return 1.0 - 0.30 * (0.5 + 0.5 * sens)
    if offset_days == 1:
        return 1.0 + 0.22 * sens
    return 1.0


# ---------------------------------------------------------------------------
# Promo window planner
# ---------------------------------------------------------------------------

def _plan_promos(
    market_id: str, sku: str, years: list[int], rng: random.Random,
) -> set[date]:
    """Pick promo dates for one (market, sku) across the seed window."""
    promo_days: set[date] = set()
    for year in years:
        n_windows = rng.randint(*PROMO_WINDOWS_PER_YEAR)
        for _ in range(n_windows):
            length = rng.randint(*PROMO_WINDOW_LENGTH)
            # Random start day inside this year, leaving room for the window
            day_of_year = rng.randint(1, 365 - length)
            try:
                first = date(year, 1, 1) + timedelta(days=day_of_year - 1)
            except ValueError:
                continue
            for k in range(length):
                promo_days.add(first + timedelta(days=k))
    return promo_days


def _promo_lift(rng: random.Random) -> float:
    return rng.uniform(*PROMO_LIFT)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def fetch_products() -> list[tuple[str, str]]:
    """Return [(sku, category)] for every row in `products`."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT sku, category FROM products ORDER BY sku")).all()
    return [(r.sku, r.category) for r in rows]


def fetch_markets() -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT market_id FROM markets ORDER BY market_id"
        )).all()
    return [r.market_id for r in rows]


def _date_index(start: date, end: date) -> list[date]:
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def generate_demand_rows(
    products: list[tuple[str, str]],
    markets: list[str],
    start: date,
    end: date,
) -> Iterable[tuple]:
    """Stream demand rows. We yield bytes-ready tuples so the caller can pipe
    them straight into a COPY without holding the whole 200 k-row list."""

    days = _date_index(start, end)

    # Pre-compute Ramadan/Eid lookups for every relevant year
    years_in_window = sorted({d.year for d in days})
    # Allow lookups one year forward (pre-Ramadan stockup spans year boundary).
    extra_years = years_in_window + [max(years_in_window) + 1]

    ramadan_day_by_date: dict[date, int] = {}
    pre_ramadan_by_date: dict[date, int] = {}  # value = days_before (1..7)
    eid_alfitr_offset: dict[date, int] = {}
    eid_aladha_offset: dict[date, int] = {}

    for y in extra_years:
        for d, idx in cal.ramadan_days(y):
            ramadan_day_by_date[d] = idx
        for n, d in enumerate(cal.pre_ramadan_stockup_dates(y), start=1):
            # Last entry in the list is the day immediately before Ramadan.
            # n=1 → 7 days before; n=7 → 1 day before. Convert to days_before:
            days_before = cal.PRE_RAMADAN_STOCKUP_DAYS - n + 1
            pre_ramadan_by_date[d] = days_before
        if y in cal.EID_ALFITR:
            ed = cal.EID_ALFITR[y]
            for off in (-1, 0, 1):
                eid_alfitr_offset[ed + timedelta(days=off)] = off
        if y in cal.EID_ALADHA:
            ed = cal.EID_ALADHA[y]
            for off in (-1, 0, 1):
                eid_aladha_offset[ed + timedelta(days=off)] = off

    rng = random.Random(RNG_SEED)
    np_rng = np.random.default_rng(RNG_SEED)

    log.info("planned: %d markets x %d products x %d days = %d rows",
             len(markets), len(products), len(days),
             len(markets) * len(products) * len(days))

    for market_id in markets:
        for sku, category in products:
            base = _baseline_units(market_id, category)
            price = _price_for(sku, category)
            promo_days = _plan_promos(market_id, sku, list(years_in_window), rng)
            # Pre-sample noise & promo lifts in vector form for speed.
            noise = np_rng.normal(loc=1.0, scale=NOISE_SIGMA, size=len(days))
            for i, d in enumerate(days):
                factor = (
                    _yoy_factor(market_id, d)
                    * _weekday_factor(d)
                    * _yearly_seasonality(market_id, d)
                )
                if d in ramadan_day_by_date:
                    factor *= _ramadan_factor(category, market_id, ramadan_day_by_date[d])
                if d in pre_ramadan_by_date:
                    factor *= _pre_ramadan_factor(category, market_id, pre_ramadan_by_date[d])
                if d in eid_alfitr_offset:
                    factor *= _eid_alfitr_factor(category, market_id, eid_alfitr_offset[d])
                if d in eid_aladha_offset:
                    factor *= _eid_aladha_factor(category, market_id, eid_aladha_offset[d])

                promo = d in promo_days
                if promo:
                    factor *= 1.0 + _promo_lift(rng)

                expected = base * factor * float(noise[i])
                units = max(0, int(round(expected)))
                revenue = round(units * price, 2)

                yield (d, market_id, sku, units, revenue, promo, None)


# ---------------------------------------------------------------------------
# COPY helpers
# ---------------------------------------------------------------------------

def _copy_demand(rows: Iterable[tuple]) -> int:
    """Stream rows into demand_history via COPY ... FROM STDIN. Returns count."""
    raw = engine.raw_connection()
    n = 0
    try:
        cur = raw.cursor()
        buf = io.StringIO()
        for r in rows:
            d, market, sku, units, revenue, promo, notes = r
            buf.write(f"{d.isoformat()}\t{market}\t{sku}\t{units}\t{revenue}\t"
                      f"{'t' if promo else 'f'}\t{notes if notes else ''}\n")
            n += 1
            # Flush in 50 k-row batches to keep memory bounded.
            if n % 50_000 == 0:
                buf.seek(0)
                cur.copy_expert(
                    "COPY demand_history (date, market_id, product_id, units_sold, "
                    "revenue, promo_active, notes) FROM STDIN WITH (FORMAT text, NULL '')",
                    buf,
                )
                buf = io.StringIO()
        if buf.tell() > 0:
            buf.seek(0)
            cur.copy_expert(
                "COPY demand_history (date, market_id, product_id, units_sold, "
                "revenue, promo_active, notes) FROM STDIN WITH (FORMAT text, NULL '')",
                buf,
            )
        raw.commit()
    finally:
        raw.close()
    return n


def _copy_calendar(rows: list[tuple]) -> int:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        buf = io.StringIO()
        for r in rows:
            d, is_ram, rday, fitr, adha, pre, hol = r
            buf.write(f"{d.isoformat()}\t{'t' if is_ram else 'f'}\t"
                      f"{rday if rday is not None else ''}\t"
                      f"{'t' if fitr else 'f'}\t{'t' if adha else 'f'}\t"
                      f"{'t' if pre else 'f'}\t{hol if hol else ''}\n")
        buf.seek(0)
        cur.copy_expert(
            "COPY demand_calendar (date, is_ramadan, ramadan_day, is_eid_alfitr, "
            "is_eid_aladha, is_pre_ramadan_stockup, holiday_name) "
            "FROM STDIN WITH (FORMAT text, NULL '')",
            buf,
        )
        raw.commit()
    finally:
        raw.close()
    return len(rows)


def truncate_all() -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE demand_history;"))
        conn.execute(text("TRUNCATE demand_calendar;"))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

VERIFY_QUERIES: list[tuple[str, str]] = [
    ("Total demand_history rows", "SELECT COUNT(*) AS n FROM demand_history;"),
    ("Per-market row count",
     "SELECT market_id, COUNT(*) AS n FROM demand_history GROUP BY 1 ORDER BY 1;"),
    ("Demand calendar rows",
     "SELECT COUNT(*) AS n, SUM(is_ramadan::int) AS ramadan_days, "
     "SUM(is_eid_alfitr::int) AS fitr_days, SUM(is_eid_aladha::int) AS adha_days, "
     "SUM(is_pre_ramadan_stockup::int) AS pre_stockup_days "
     "FROM demand_calendar;"),
    ("UAE Facial Tissue 100ct around Ramadan 2024 (10 days from Mar 8 → Mar 18)",
     "SELECT date, units_sold, revenue, promo_active "
     "FROM demand_history "
     "WHERE market_id='uae' AND product_id='fine-facial-100' "
     "  AND date BETWEEN '2024-03-08' AND '2024-03-18' "
     "ORDER BY date;"),
    ("UAE Facial Tissue 100ct — monthly totals 2024 (Ramadan-month should peak)",
     "SELECT date_trunc('month', date)::date AS month, SUM(units_sold) AS units "
     "FROM demand_history "
     "WHERE market_id='uae' AND product_id='fine-facial-100' "
     "  AND date BETWEEN '2024-01-01' AND '2024-12-31' "
     "GROUP BY 1 ORDER BY 1;"),
    ("YoY growth check 2023 → 2024 by market",
     "WITH y AS ( "
     "  SELECT market_id, EXTRACT(YEAR FROM date)::int AS yr, SUM(units_sold) AS units "
     "  FROM demand_history GROUP BY 1, 2 "
     ") "
     "SELECT a.market_id, a.units AS y2023, b.units AS y2024, "
     "       round(100.0 * (b.units - a.units) / a.units, 2) AS pct_growth "
     "FROM y a JOIN y b USING (market_id) "
     "WHERE a.yr=2023 AND b.yr=2024 ORDER BY market_id;"),
    ("KSA Facial Tissue 100ct around Eid al-Fitr 2024 (Apr 8 → Apr 12 spike-dip-bounce)",
     "SELECT date, units_sold, promo_active "
     "FROM demand_history "
     "WHERE market_id='ksa' AND product_id='fine-facial-100' "
     "  AND date BETWEEN '2024-04-08' AND '2024-04-12' "
     "ORDER BY date;"),
]


def run_verification() -> None:
    log.info("=== verification queries ===")
    with engine.connect() as conn:
        for label, sql in VERIFY_QUERIES:
            log.info("--- %s ---", label)
            rows = conn.execute(text(sql)).all()
            for r in rows:
                log.info("  %s", dict(r._mapping))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--truncate", action="store_true",
                   help="Wipe demand_history and demand_calendar before seeding.")
    p.add_argument("--count", action="store_true",
                   help="Dry-run; print expected row count and exit.")
    p.add_argument("--verify", action="store_true",
                   help="Run verification queries only, no seeding.")
    args = p.parse_args()

    t0 = time.perf_counter()

    log.info("applying schema...")
    apply_schema()

    if args.verify:
        run_verification()
        return 0

    products = fetch_products()
    markets = fetch_markets()
    days = (END_DATE - START_DATE).days + 1
    expected_rows = len(markets) * len(products) * days
    log.info("markets=%d products=%d days=%d => expected rows=%d",
             len(markets), len(products), days, expected_rows)

    if args.count:
        return 0

    if args.truncate:
        log.info("truncating demand_history + demand_calendar...")
        truncate_all()

    # Calendar
    log.info("seeding demand_calendar...")
    cal_rows = generate_calendar_rows(START_DATE, END_DATE)
    n_cal = _copy_calendar(cal_rows)
    log.info("demand_calendar rows: %d  (%.1fs)", n_cal, time.perf_counter() - t0)

    # Demand history (streamed COPY)
    log.info("seeding demand_history... (streaming COPY)")
    t1 = time.perf_counter()
    n_dem = _copy_demand(generate_demand_rows(products, markets, START_DATE, END_DATE))
    log.info("demand_history rows: %d  (%.1fs)", n_dem, time.perf_counter() - t1)

    log.info("TOTAL %.1fs", time.perf_counter() - t0)
    run_verification()
    return 0


if __name__ == "__main__":
    sys.exit(main())
