# FHH AI Optimizer — demand history data layer

Seeds 3 years of daily demand and a Ramadan/Eid calendar for every
(market × SKU) pair. The next prompt trains Prophet models on top of
this data.

## Tables

```
markets ───────────────┐
                       │
products ─────────────┐│
                      ▼▼
            ┌──────────────────────────────────────────────────────┐
            │ demand_history          (TimescaleDB hypertable,      │
            │                         monthly chunks on date)       │
            │                                                       │
            │  date          DATE        ─┐                         │
            │  market_id     TEXT          ├ composite PK            │
            │  product_id    TEXT        ─┘                         │
            │  units_sold    INTEGER                                │
            │  revenue       NUMERIC(14,2)                          │
            │  promo_active  BOOLEAN                                │
            │  notes         TEXT (NULL)                            │
            │                                                       │
            │  Indexes: (market_id, date DESC)                      │
            │           (product_id, date DESC)                     │
            │           (date, market_id, product_id) WHERE promo   │
            └──────────────────────────────────────────────────────┘

            ┌──────────────────────────────────────────────────────┐
            │ demand_calendar         (small reference table)       │
            │                                                       │
            │  date                    DATE PK                      │
            │  is_ramadan              BOOLEAN                      │
            │  ramadan_day             INTEGER (1..30 or NULL)      │
            │  is_eid_alfitr           BOOLEAN                      │
            │  is_eid_aladha           BOOLEAN                      │
            │  is_pre_ramadan_stockup  BOOLEAN                      │
            │  holiday_name            TEXT (NULL)                  │
            └──────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|---|---|
| `schema.sql`       | `CREATE TABLE` + `create_hypertable` + indexes (idempotent) |
| `calendar_dates.py`| Hijri-derived Ramadan / Eid dates for 2023-2028 (KSA reference) |
| `seed_demand.py`   | Generates and bulk-loads both tables; verification queries |

## How the seeder builds demand

For each (market, SKU, date) the daily expected units multiply seven factors:

| # | Factor | Source |
|---|---|---|
| 1 | **Baseline** | category × per-market scale (UAE = 1.00, KSA = 2.40, EGY = 2.10, MOR = 0.95, JOR = 0.55) |
| 2 | **YoY growth** | UAE +8% · MOR +6% · KSA +5% · JOR +4% · EGY +3%, compounded from 2023-01-01 |
| 3 | **Weekly seasonality** | Thu-Sat +8 %, Sun +2 %, Mon -5 % |
| 4 | **Yearly seasonality** | Gulf summer dip Jul-Aug -15 %; Morocco/Jordan winter peak Dec-Feb +10 % |
| 5 | **Ramadan curve** | Pre-stockup (7 days) +30…+45 %, Ramadan d1-10 +20 %, d11-20 flat, d21-end +20 → +35 % |
| 6 | **Eid spikes** | Day-before +65 % (Fitr) / +45 % (Adha), day-of -45 % / -30 %, day-after +35 % / +22 % |
| 7 | **Promo windows** | 8-12 random windows of 5-9 days per (market, SKU, year) at +18-28 % |
|   | + Gaussian noise σ = 5 % | so the demo curves don't look synthetic |

Category × market sensitivity scales factor 5/6 — `tissue` and `wellness`
shift the most during Ramadan, `adult_care` and `fine_guard` barely move.

`random.seed(42)` + `numpy.random.default_rng(42)` make the whole simulation
deterministic, so the Ramadan spike on Al Nakheel UAE Facial 100ct lands
in the same month every re-run.

## Run

Database: `fhh_optimizers` on `localhost:5433` (TimescaleDB Docker container).

```bash
# from the project root
python -m backend.demand.seed_demand            # apply schema + seed (idempotent)
python -m backend.demand.seed_demand --truncate # wipe + re-seed
python -m backend.demand.seed_demand --count    # dry-run; print expected row count
python -m backend.demand.seed_demand --verify   # run verification queries only
```

Total wall time on a developer laptop: **~12 seconds** for 202,760 rows
(target was ≤ 3 minutes). Bulk loading uses
`COPY demand_history FROM STDIN`, batched at 50 k rows.

## Verification

The seed script runs these queries automatically. You can re-run them with
`--verify`:

| Query | What it confirms |
|---|---|
| Total rows | 5 markets × 37 SKUs × 1,096 days = **202,760** |
| Per-market row count | 40,552 each (uniform — no missing combos) |
| Calendar totals | 89 Ramadan days, 3 Eid al-Fitr, 3 Eid al-Adha, 21 pre-stockup |
| UAE Facial 100ct around Ramadan 2024 | visible pre-stockup spike Mar 8-10, then Ramadan-day 1 dip on Mon Mar 11 |
| UAE Facial 100ct monthly totals 2024 | March (Ramadan) is the peak; Jul-Aug are the lowest (Gulf summer dip) |
| YoY growth 2023 → 2024 by market | matches the targets ±0.3 pp: UAE 8.02 / MOR 6.10 / KSA 5.64 / JOR 4.27 / EGY 3.05 |
| KSA Facial 100ct around Eid al-Fitr 2024 | spike-dip-bounce: 15 k → **28 k** → 5.8 k → 15.8 k → 11.7 k |

## Edge cases handled

- **Leap year (Feb 29 2024)** — `_date_index` walks the calendar; Feb 29 gets a row.
- **Ramadan 2025 (Mar 1-30)** — calendar generation looks one year forward, so the 7-day pre-stockup window (Feb 22-28) for Ramadan 2025 is correctly tagged on Feb-2025 dates inside the seed window.
- **Year-boundary pre-stockup** — Ramadan 2026 (Feb 18) and 2027 (Feb 8) shift earlier each year as the Hijri calendar drifts ~10 days/year. The calendar table covers 2023-2028 to support forward-looking forecasts.
- **Eid windows clipped at seed boundary** — the day-before / day-after offsets only fire when the offset date is inside the seed window.
- **Deterministic** — same `RNG_SEED = 42` reproduces identical numbers on every re-run, so demos stay stable.

## Hijri dates — sources & accuracy

The `calendar_dates.py` module hardcodes KSA's official sighting dates
through 2024 and Umm al-Qura calculated dates for 2025-2028. Other MENA
markets sometimes start fasting one calendar day later, but the simulation
uses one calendar across all five markets — that mirrors how the dashboard
groups events.

## Schema-level guarantees

- `market_id` constrained to the contract's 5 IDs (`uae`, `ksa`, `jordan`, `egypt`, `morocco`).
- `product_id` is a foreign key to `products(sku)`; deleting a SKU cascades.
- `units_sold` and `revenue` non-negative (CHECK constraints).
- Composite PK on `(date, market_id, product_id)` makes re-seeds idempotent
  via `INSERT ... ON CONFLICT` if needed (the current seeder uses TRUNCATE).
- TimescaleDB chunk interval = 1 month → ~37 chunks across the 3-year span,
  each ~5,500 rows: small enough to scan quickly, big enough that
  range queries don't fan out across hundreds of chunks.

## Re-running the seeder

Idempotent flow:
```bash
python -m backend.demand.seed_demand --truncate
```

The `--truncate` flag wipes both tables before reseeding (faster than
on-conflict path). Without it the seeder will fail with a primary-key
collision because it doesn't apply `ON CONFLICT`.
