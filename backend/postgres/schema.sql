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

COMMIT;
