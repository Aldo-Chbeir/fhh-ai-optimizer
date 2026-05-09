-- 0002_calendar.sql -- Calendar tab DB foundation.
--
-- Adds two tables to back the new Calendar tab:
--
--   1. material_orders         -- raw-material orders for a SKU. Written by
--                                 the Demand tab's "Schedule Order" action.
--   2. calendar_events_custom  -- ad-hoc user events not tied to alerts /
--                                 maintenance / orders / production runs.
--
-- Idempotent -- safe to re-run.

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. material_orders
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_orders (
    order_id              TEXT         PRIMARY KEY,
    sku                   TEXT         NOT NULL REFERENCES products(sku),
    market                TEXT                  REFERENCES markets(market_id),
    quantity              NUMERIC      NOT NULL,
    unit                  TEXT         NOT NULL DEFAULT 'units',
    order_date            DATE         NOT NULL,
    expected_arrival_date DATE         NOT NULL,
    status                TEXT         NOT NULL DEFAULT 'pending'
                                       CHECK (status IN ('pending','ordered','in_transit','delivered','cancelled')),
    created_by            TEXT,
    notes                 TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_material_orders_arrival
    ON material_orders (expected_arrival_date);
CREATE INDEX IF NOT EXISTS idx_material_orders_sku_market
    ON material_orders (sku, market);
CREATE INDEX IF NOT EXISTS idx_material_orders_status
    ON material_orders (status);

-- ----------------------------------------------------------------------------
-- 2. calendar_events_custom
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calendar_events_custom (
    event_id          TEXT         PRIMARY KEY,
    title             TEXT         NOT NULL,
    event_date        DATE         NOT NULL,
    event_time        TIME,
    duration_minutes  INTEGER,
    machine_id        TEXT         REFERENCES machines(machine_id) ON DELETE CASCADE,
    event_type        TEXT         NOT NULL
                                   CHECK (event_type IN ('inspection','meeting','training','audit','visit','other')),
    notes             TEXT,
    created_by        TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_calendar_events_date
    ON calendar_events_custom (event_date);
CREATE INDEX IF NOT EXISTS idx_calendar_events_machine_date
    ON calendar_events_custom (machine_id, event_date);

COMMIT;
