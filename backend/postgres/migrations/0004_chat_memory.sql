-- 0004_chat_memory.sql — per-user chat conversation history.
-- Builds on 0003_app_users (chat_conversations.user_id FKs into app_users).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS chat_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    title           VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conv_user_updated
    ON chat_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role                VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT NOT NULL,
    data_sources_used   JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conv_created
    ON chat_messages(conversation_id, created_at);

-- Bump conversations.updated_at every time a message is appended so the
-- "Recent Chats" list orders by genuine activity instead of first-message
-- time. Runs server-side so the API layer doesn't need to remember.
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
