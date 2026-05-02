-- 0001_alert_status.sql — persist alert state (audit finding
-- "alert-actions-localstorage-only").
--
-- Adds the four columns the API + UI need to track alert state through
-- the full triage workflow (active → acknowledged / scheduled / snoozed
-- → resolved). Idempotent — safe to re-run.

BEGIN;

-- 1. New columns -----------------------------------------------------------
ALTER TABLE alarm_events
    ADD COLUMN IF NOT EXISTS status              TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS status_changed_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS status_changed_by   TEXT,
    ADD COLUMN IF NOT EXISTS status_metadata     JSONB NOT NULL DEFAULT '{}'::jsonb;

-- 2. Constrain `status` to the five valid values --------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.constraint_column_usage
        WHERE constraint_name = 'alarm_events_status_check'
    ) THEN
        ALTER TABLE alarm_events
            ADD CONSTRAINT alarm_events_status_check
            CHECK (status IN ('active', 'acknowledged', 'scheduled', 'snoozed', 'resolved'));
    END IF;
END $$;

-- 3. Backfill ---------------------------------------------------------------
-- Pre-existing rows: rows that already had `resolved_at` set are now
-- marked status='resolved'; everything else stays 'active' (the column
-- default already gave them that on add).
UPDATE alarm_events
SET status = 'resolved',
    status_changed_at = COALESCE(status_changed_at, resolved_at),
    status_changed_by = COALESCE(status_changed_by, 'system')
WHERE resolved_at IS NOT NULL
  AND status = 'active';

-- 4. Index for the alerts list query --------------------------------------
CREATE INDEX IF NOT EXISTS idx_alarm_events_status_machine
    ON alarm_events (status, machine_id);

CREATE INDEX IF NOT EXISTS idx_alarm_events_status_changed_at
    ON alarm_events (status_changed_at DESC);

COMMIT;
