-- FHH AI Optimizer — PostgreSQL relational schema
-- Conforms to API_CONTRACT.md v1.1
-- All field names, enum values, IDs are taken verbatim from the contract.

BEGIN;

-- ----------------------------------------------------------------------------
-- machines
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machines (
    machine_id            TEXT PRIMARY KEY
                          CHECK (machine_id IN ('al-nakheel','al-bardi','al-sindian','al-snobar')),
    name                  TEXT         NOT NULL,
    location              TEXT         NOT NULL,
    model                 TEXT         NOT NULL,
    installation_date     DATE         NOT NULL,
    status                TEXT         NOT NULL
                          CHECK (status IN ('running','idle','maintenance','offline')),
    current_speed_mpm     INTEGER      NOT NULL DEFAULT 0,
    current_oee_percent   NUMERIC(5,2) NOT NULL DEFAULT 0
);

-- ----------------------------------------------------------------------------
-- components (composite PK: one row per (machine, component))
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS components (
    component_id                  TEXT     NOT NULL
                                  CHECK (component_id IN
                                    ('headbox','visconip','yankee','aircap','softreel','rewinder')),
    machine_id                    TEXT     NOT NULL
                                  REFERENCES machines(machine_id) ON DELETE CASCADE,
    name                          TEXT     NOT NULL,
    is_critical                   BOOLEAN  NOT NULL DEFAULT FALSE,
    expected_lifetime_hours       INTEGER  NOT NULL,
    hours_since_last_maintenance  INTEGER  NOT NULL DEFAULT 0,
    last_maintenance_date         DATE,
    PRIMARY KEY (machine_id, component_id)
);

-- ----------------------------------------------------------------------------
-- production_runs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS production_runs (
    run_id          TEXT          PRIMARY KEY,
    machine_id      TEXT          NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    start_time      TIMESTAMPTZ   NOT NULL,
    end_time        TIMESTAMPTZ,
    product_grade   TEXT          NOT NULL,
    tons_produced   NUMERIC(10,2) NOT NULL DEFAULT 0,
    oee_percent     NUMERIC(5,2)  NOT NULL DEFAULT 0,
    shift           TEXT          NOT NULL CHECK (shift IN ('morning','afternoon','night'))
);
CREATE INDEX IF NOT EXISTS idx_production_runs_machine_time
    ON production_runs (machine_id, start_time DESC);

-- ----------------------------------------------------------------------------
-- maintenance_logs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS maintenance_logs (
    log_id            TEXT          PRIMARY KEY,
    component_id      TEXT          NOT NULL,
    machine_id        TEXT          NOT NULL,
    maintenance_type  TEXT          NOT NULL
                      CHECK (maintenance_type IN ('preventive','corrective','predictive','emergency')),
    date_performed    DATE          NOT NULL,
    cost_usd          NUMERIC(12,2) NOT NULL DEFAULT 0,
    downtime_hours    NUMERIC(6,2)  NOT NULL DEFAULT 0,
    technician        TEXT,
    notes             TEXT,
    FOREIGN KEY (machine_id, component_id)
        REFERENCES components (machine_id, component_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_maintenance_logs_machine
    ON maintenance_logs (machine_id, date_performed DESC);

-- ----------------------------------------------------------------------------
-- alarm_events  (Valmet DNA DCS alarm stream)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alarm_events (
    alarm_id          TEXT         PRIMARY KEY,
    machine_id        TEXT         NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    timestamp         TIMESTAMPTZ  NOT NULL,
    severity          TEXT         NOT NULL CHECK (severity IN ('info','warning','critical')),
    description       TEXT         NOT NULL,
    resolved_at       TIMESTAMPTZ,
    downtime_minutes  INTEGER      NOT NULL DEFAULT 0,
    status            TEXT         NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active','acknowledged','scheduled','snoozed','resolved')),
    status_changed_at TIMESTAMPTZ,
    status_changed_by TEXT,
    status_metadata   JSONB        NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_alarm_events_machine_time
    ON alarm_events (machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alarm_events_unresolved
    ON alarm_events (machine_id) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_alarm_events_status_machine
    ON alarm_events (status, machine_id);
CREATE INDEX IF NOT EXISTS idx_alarm_events_status_changed_at
    ON alarm_events (status_changed_at DESC);

-- ----------------------------------------------------------------------------
-- quality_scans  (QCS readings, hourly per active run)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quality_scans (
    scan_id           TEXT         PRIMARY KEY,
    run_id            TEXT         NOT NULL REFERENCES production_runs(run_id) ON DELETE CASCADE,
    timestamp         TIMESTAMPTZ  NOT NULL,
    basis_weight_gsm  NUMERIC(6,2),
    moisture_percent  NUMERIC(5,2),
    softness_index    NUMERIC(5,2),
    caliper_microns   NUMERIC(6,2)
);
CREATE INDEX IF NOT EXISTS idx_quality_scans_run
    ON quality_scans (run_id, timestamp);

-- ----------------------------------------------------------------------------
-- products  (37 SKUs for the demand module)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    sku       TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL
              CHECK (category IN
                ('tissue','baby_care','adult_care','fine_guard','wellness','cosmetics')),
    unit      TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- markets  (5 MENA markets)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS markets (
    market_id  TEXT PRIMARY KEY
               CHECK (market_id IN ('jordan','egypt','uae','ksa','morocco')),
    name       TEXT NOT NULL,
    currency   TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- material_orders  (raw-material orders for a SKU; written by Demand tab)
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
-- calendar_events_custom  (ad-hoc Calendar-tab events not tied to alerts /
-- maintenance / orders / production runs)
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

-- ----------------------------------------------------------------------------
-- app_users  (login + role-gated /auth endpoints — see migration 0003)
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS app_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(50)  NOT NULL CHECK (role IN ('admin', 'operator')),
    full_name       VARCHAR(255),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);

-- ----------------------------------------------------------------------------
-- chat_conversations + chat_messages  (per-user chat history — see migration 0004)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID         NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    title           VARCHAR(255),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_conv_user_updated
    ON chat_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID         NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role                VARCHAR(20)  NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT         NOT NULL,
    data_sources_used   JSONB,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conv_created
    ON chat_messages(conversation_id, created_at);

CREATE OR REPLACE FUNCTION touch_chat_conversation_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE chat_conversations
    SET    updated_at = NOW()
    WHERE  id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chat_messages_touch_conversation ON chat_messages;
CREATE TRIGGER chat_messages_touch_conversation
AFTER INSERT ON chat_messages
FOR EACH ROW EXECUTE FUNCTION touch_chat_conversation_updated_at();

-- ----------------------------------------------------------------------------
-- user_maintenance_entries  (operator-logged work — see migration 0005)
-- Distinct from `maintenance_logs` (seeded historical corrective events) so
-- we can attribute each row to the user who logged it. ON DELETE RESTRICT
-- on user_id so deactivating an account doesn't silently nuke their history.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_maintenance_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID         NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,
    machine_id          VARCHAR(100) NOT NULL,
    component_id        VARCHAR(100),
    maintenance_type    VARCHAR(50)  NOT NULL CHECK (maintenance_type IN
                            ('preventive', 'corrective', 'predictive', 'inspection')),
    work_description    TEXT         NOT NULL,
    cost_usd            NUMERIC(12,2) CHECK (cost_usd IS NULL OR cost_usd >= 0),
    duration_hours      NUMERIC(6,2)  CHECK (duration_hours IS NULL OR duration_hours >= 0),
    technician_name     VARCHAR(255) NOT NULL,
    performed_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_maint_machine_id   ON user_maintenance_entries(machine_id);
CREATE INDEX IF NOT EXISTS idx_user_maint_user_id      ON user_maintenance_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_user_maint_performed_at ON user_maintenance_entries(performed_at DESC);

COMMIT;
