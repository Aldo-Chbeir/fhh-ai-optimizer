-- FHH AI Optimizer — demand forecasting schema (TimescaleDB)
-- Conforms to API_CONTRACT.md v1.1: market_id ∈ {uae, ksa, jordan, egypt, morocco}.
-- Idempotent — safe to re-run.

BEGIN;

-- ---------------------------------------------------------------------------
-- demand_history  (hypertable, monthly chunks)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demand_history (
    date          DATE          NOT NULL,
    market_id     TEXT          NOT NULL
                  CHECK (market_id IN ('uae','ksa','jordan','egypt','morocco')),
    product_id    TEXT          NOT NULL
                  REFERENCES products(sku) ON DELETE CASCADE,
    units_sold    INTEGER       NOT NULL CHECK (units_sold >= 0),
    revenue       NUMERIC(14,2) NOT NULL CHECK (revenue   >= 0),
    promo_active  BOOLEAN       NOT NULL DEFAULT FALSE,
    notes         TEXT,
    PRIMARY KEY (date, market_id, product_id)
);

-- Convert to hypertable. Monthly chunks keep range scans tight.
-- if_not_exists=true makes the call idempotent.
SELECT create_hypertable(
    'demand_history',
    'date',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE,
    migrate_data        => TRUE
);

CREATE INDEX IF NOT EXISTS idx_demand_history_market_date
    ON demand_history (market_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_demand_history_product_date
    ON demand_history (product_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_demand_history_promo
    ON demand_history (date, market_id, product_id) WHERE promo_active;

-- ---------------------------------------------------------------------------
-- demand_calendar  (small reference table — NOT a hypertable)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demand_calendar (
    date                    DATE PRIMARY KEY,
    is_ramadan              BOOLEAN NOT NULL DEFAULT FALSE,
    ramadan_day             INTEGER,                     -- 1..30 inside Ramadan, NULL otherwise
    is_eid_alfitr           BOOLEAN NOT NULL DEFAULT FALSE,
    is_eid_aladha           BOOLEAN NOT NULL DEFAULT FALSE,
    is_pre_ramadan_stockup  BOOLEAN NOT NULL DEFAULT FALSE,
    holiday_name            TEXT
);

CREATE INDEX IF NOT EXISTS idx_demand_calendar_ramadan
    ON demand_calendar (date) WHERE is_ramadan;
CREATE INDEX IF NOT EXISTS idx_demand_calendar_eid
    ON demand_calendar (date) WHERE is_eid_alfitr OR is_eid_aladha;

COMMIT;
