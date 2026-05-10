"""DB layer for chat_conversations + chat_messages — pool-first asyncpg.

Same pool-acquire-per-call pattern as backend/api/auth/services.py.

`data_sources_used` is stored as JSONB. asyncpg accepts a JSON-encoded
string for JSONB columns; we encode on the way in, decode on the way out.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import asyncpg

LIST_LIMIT = 10
TITLE_MAX_CHARS = 60


# ---------------------------------------------------------------------------
# Title helper
# ---------------------------------------------------------------------------

async def auto_title(message: str) -> str:
    """Derive a short, single-line conversation title from a user message.

    Strips newlines, collapses runs of whitespace, truncates to
    TITLE_MAX_CHARS. Empty messages fall back to 'New chat'.
    """
    cleaned = " ".join((message or "").split())
    if not cleaned:
        return "New chat"
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    return cleaned[: TITLE_MAX_CHARS - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Row → dict normalisers
# ---------------------------------------------------------------------------

def _conv_row(r) -> dict:
    return {
        "id":         str(r["id"]),
        "user_id":    str(r["user_id"]),
        "title":      r["title"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _msg_row(r) -> dict:
    raw = r["data_sources_used"]
    # asyncpg returns JSONB as a Python str; decode for the response.
    if isinstance(raw, str):
        try:
            sources = json.loads(raw)
        except Exception:  # noqa: BLE001
            sources = None
    else:
        sources = raw  # already a list/dict, or None
    return {
        "id":                str(r["id"]),
        "conversation_id":   str(r["conversation_id"]),
        "role":              r["role"],
        "content":           r["content"],
        "data_sources_used": sources,
        "created_at":        r["created_at"],
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def list_user_conversations(pool: asyncpg.Pool, user_id: UUID) -> list[dict]:
    """Return the user's last LIST_LIMIT conversations with message_count.

    One query: LEFT JOIN counts messages so brand-new (empty) conversations
    still appear with count=0.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM   chat_conversations c
            LEFT JOIN chat_messages m ON m.conversation_id = c.id
            WHERE  c.user_id = $1
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT  $2
            """,
            user_id, LIST_LIMIT,
        )
    return [
        {
            "id":            str(r["id"]),
            "title":         r["title"],
            "updated_at":    r["updated_at"],
            "message_count": int(r["message_count"]),
        }
        for r in rows
    ]


async def get_user_conversation(
    pool: asyncpg.Pool, conv_id: UUID, user_id: UUID,
) -> Optional[dict]:
    """Return the conversation iff it exists AND belongs to user_id.

    Returning None for both 'no row' and 'wrong owner' is intentional — the
    caller surfaces a 404 without distinguishing the two cases.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM chat_conversations WHERE id = $1 AND user_id = $2",
            conv_id, user_id,
        )
    return _conv_row(row) if row else None


async def get_conversation_messages(
    pool: asyncpg.Pool, conv_id: UUID,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM chat_messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            conv_id,
        )
    return [_msg_row(r) for r in rows]


async def conversation_history_for_model(
    pool: asyncpg.Pool, conv_id: UUID,
) -> list[dict]:
    """Anthropic-shaped {role, content} list for feeding back into the
    tool-use loop on the next turn. Newest message LAST."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content FROM chat_messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            conv_id,
        )
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def delete_user_conversation(
    pool: asyncpg.Pool, conv_id: UUID, user_id: UUID,
) -> bool:
    """Returns True if a row was deleted. Cascade FK clears chat_messages."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_conversations WHERE id = $1 AND user_id = $2",
            conv_id, user_id,
        )
    return result.endswith(" 1")


async def ensure_conversation_for_user(
    pool: asyncpg.Pool,
    *,
    user_id: UUID,
    conversation_id: Optional[str],
    first_message: str,
) -> dict:
    """Resolve the conversation for a chat turn.

      - conversation_id given AND owned by user → return existing conv.
      - conversation_id given but not owned (or doesn't exist) → return
        None upstream so the router can 404 (single message — no leak).
      - conversation_id is None → create a fresh conv titled from the
        first message and return it.

    The 'not owned → 404' branch is signalled by raising ValueError so the
    router can convert to a contract-shaped 404 (`ConversationNotFound`).
    """
    if conversation_id:
        try:
            cid = UUID(conversation_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("conversation_not_found") from exc
        existing = await get_user_conversation(pool, cid, user_id)
        if existing is None:
            raise ValueError("conversation_not_found")
        return existing

    title = await auto_title(first_message)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_conversations (user_id, title)
            VALUES ($1, $2)
            RETURNING *
            """,
            user_id, title,
        )
    return _conv_row(row)


async def persist_user_turn(
    pool: asyncpg.Pool, conversation_id: UUID, content: str,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_messages (conversation_id, role, content)
            VALUES ($1, 'user', $2)
            RETURNING *
            """,
            conversation_id, content,
        )
    return _msg_row(row)


async def persist_assistant_turn(
    pool: asyncpg.Pool,
    conversation_id: UUID,
    content: str,
    data_sources_used: Optional[list[Any]] = None,
) -> dict:
    # JSONB column wants a JSON-encoded string (or NULL).
    sources_json = json.dumps(data_sources_used) if data_sources_used else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_messages (conversation_id, role, content, data_sources_used)
            VALUES ($1, 'assistant', $2, $3::jsonb)
            RETURNING *
            """,
            conversation_id, content, sources_json,
        )
    return _msg_row(row)
