-- 0007_calendar_scheduled_maintenance.sql — distinguish proactive maintenance
-- events (created by the Machine Detail "Schedule Maintenance" button) from
-- arbitrary custom events (meetings, training, audits) so the calendar UI can
-- render the right badge.
--
-- `is_scheduled_maintenance` is the discriminator the feed adapter checks.
-- `component_id` and `technician` are nullable companions so the existing
-- EventDetailModal can show the same fields it already shows for alert-
-- scheduled maintenance rows (sourced from alarm_events.status_metadata).
--
-- Idempotent: safe to re-run.

ALTER TABLE calendar_events_custom
    ADD COLUMN IF NOT EXISTS is_scheduled_maintenance BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS component_id TEXT,
    ADD COLUMN IF NOT EXISTS technician   TEXT;
