-- FHH AI Optimizer — TimescaleDB sensor data layer
-- Conforms to API_CONTRACT.md v1.1
--
-- Apply ONLY after backend/postgres/schema.sql has been applied to the same DB
-- (this script depends on the `machines` and `maintenance_logs` tables existing).
--
-- Note on component_id integrity: the contract defines 14 sensor_types, one
-- of which (`qcs_softness_index`) belongs to component "qcs" — and "qcs" is
-- NOT one of the 6 line components in the components table. We therefore
-- enforce component_id integrity via CHECK rather than a composite FK to
-- components(machine_id, component_id), since (machine_id, 'qcs') doesn't
-- exist there. machine_id remains a true FK so machine-level integrity is
-- preserved.

-- ============================================================================
-- 1. Enable TimescaleDB
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 2. sensor_readings  — high-volume time-series, hypertable
-- ============================================================================
CREATE TABLE IF NOT EXISTS sensor_readings (
    timestamp     TIMESTAMPTZ      NOT NULL,
    machine_id    TEXT             NOT NULL
                  REFERENCES machines(machine_id) ON DELETE CASCADE,
    component_id  TEXT             NOT NULL
                  CHECK (component_id IN
                    ('headbox','visconip','yankee','aircap','softreel','rewinder','qcs')),
    sensor_type   TEXT             NOT NULL
                  CHECK (sensor_type IN (
                    'yankee_surface_temp','yankee_steam_pressure',
                    'yankee_vibration_bearing_1','yankee_vibration_bearing_2','yankee_vibration_bearing_3',
                    'yankee_blade_pressure',
                    'visconip_nip_pressure','visconip_felt_moisture',
                    'aircap_inlet_temp','aircap_energy',
                    'headbox_stock_temp','softreel_tension','rewinder_speed',
                    'qcs_softness_index'
                  )),
    value         DOUBLE PRECISION NOT NULL,
    unit          TEXT             NOT NULL,
    is_anomaly    BOOLEAN          NOT NULL DEFAULT FALSE
);

-- Convert to hypertable with 1-day chunks
SELECT create_hypertable(
    'sensor_readings',
    'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_machine_sensor_time
    ON sensor_readings (machine_id, sensor_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_time
    ON sensor_readings (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_anomaly
    ON sensor_readings (machine_id, sensor_type, timestamp DESC) WHERE is_anomaly = TRUE;

-- ============================================================================
-- 3. Continuous aggregate — hourly rollups (min/max/avg/std per machine+sensor)
-- ============================================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_readings_hourly
WITH (timescaledb.continuous) AS
SELECT
    machine_id,
    sensor_type,
    time_bucket(INTERVAL '1 hour', timestamp) AS bucket,
    MIN(value)    AS min_value,
    MAX(value)    AS max_value,
    AVG(value)    AS avg_value,
    STDDEV(value) AS std_value,
    COUNT(*)      AS sample_count
FROM sensor_readings
GROUP BY machine_id, sensor_type, bucket
WITH NO DATA;

-- Refresh hourly; keep aggregates up to date with a 1h lag
SELECT add_continuous_aggregate_policy(
    'sensor_readings_hourly',
    start_offset => INTERVAL '14 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================================================
-- 4. Retention — drop raw rows older than 12 months (aggregates kept indefinitely)
-- ============================================================================
SELECT add_retention_policy(
    'sensor_readings',
    INTERVAL '12 months',
    if_not_exists => TRUE
);

-- ============================================================================
-- 5. Convert maintenance_logs (from the relational schema) to a hypertable
-- ----------------------------------------------------------------------------
-- The original PK is `log_id` alone. TimescaleDB requires the partitioning
-- column (`date_performed`) to be part of any UNIQUE constraint, so we drop
-- the PK and recreate it as composite.
-- ============================================================================
DO $$
BEGIN
    -- Drop the existing PK if it's still single-column
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'maintenance_logs_pkey' AND conrelid = 'maintenance_logs'::regclass
    ) THEN
        ALTER TABLE maintenance_logs DROP CONSTRAINT maintenance_logs_pkey;
        ALTER TABLE maintenance_logs
            ADD CONSTRAINT maintenance_logs_pkey PRIMARY KEY (log_id, date_performed);
    END IF;
END $$;

-- Convert to hypertable; 1-month chunks suit low-volume maintenance data
SELECT create_hypertable(
    'maintenance_logs',
    'date_performed',
    chunk_time_interval => INTERVAL '1 month',
    migrate_data => TRUE,
    if_not_exists => TRUE
);
