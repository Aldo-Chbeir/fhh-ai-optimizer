-- 0005_user_maintenance_entries.sql — operator-logged maintenance work.
-- Distinct from `maintenance_logs` (seeded historical corrective events) so
-- we can attribute each row to the user who logged it and never lose
-- entries when an account is deleted (RESTRICT, not CASCADE).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS user_maintenance_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES app_users(id) ON DELETE RESTRICT,

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
