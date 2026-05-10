-- 0006_email_notifications.sql — audit log + dedupe for outbound transactional email.
-- Each row records a single (notification_type, source_id, recipient) triple so
-- a duplicate alert webhook / re-fire of the same scheduled-maintenance event
-- can't double-mail the operator. Test emails use a fresh uuid per call so they
-- don't dedupe.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS email_notifications_sent (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_type   VARCHAR(50)  NOT NULL CHECK (notification_type IN (
                            'alert_critical', 'alert_warning',
                            'maintenance_scheduled', 'maintenance_logged',
                            'order_placed', 'test'
                        )),
    -- The "thing" being notified about (alert_id, scheduled_id, entry_id, etc.).
    -- Stored as text since different sources have different id types (UUID vs alm-… vs mat-ord-…).
    source_id           VARCHAR(255) NOT NULL,
    recipient           VARCHAR(255) NOT NULL,
    subject             TEXT         NOT NULL,
    sent_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    success             BOOLEAN      NOT NULL DEFAULT TRUE,
    resend_id           VARCHAR(255),
    error_message       TEXT,
    UNIQUE (notification_type, source_id, recipient)
);

CREATE INDEX IF NOT EXISTS idx_email_notif_type_source
    ON email_notifications_sent(notification_type, source_id);
CREATE INDEX IF NOT EXISTS idx_email_notif_sent_at
    ON email_notifications_sent(sent_at DESC);
