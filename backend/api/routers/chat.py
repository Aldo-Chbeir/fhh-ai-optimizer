"""Chat router — POST /chat (proxied to Anthropic with tool-use) and the
cold-start /chat/suggested-prompts endpoint.

Conversation listing / retrieval / delete now live in
backend/api/chat_memory/router.py (Postgres-backed, per-user). This file
just owns the user→Anthropic turn loop, persisting each turn through the
chat_memory service helpers so the assistant has memory across requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.responses import JSONResponse

from ..auth.dependencies import get_current_user
from ..chat_memory.services import (
    conversation_history_for_model, ensure_conversation_for_user,
    persist_assistant_turn, persist_user_turn,
)
from ..db import get_conn, get_pool
from ..errors import ConversationNotFound
from ..models import ChatRequest, ChatResponse, SuggestedPrompts
from ..services import chat as chat_service

router = APIRouter(tags=["chat"])


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_pool_dep() -> asyncpg.Pool:
    return get_pool()


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    body: ChatRequest = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
    user: dict = Depends(get_current_user),
):
    """Proxy a single user turn to Anthropic, persisting both sides.

    Auth is required (Phase A). The conversation is owned by `user.id`:

      - `conversation_id` absent → new conversation auto-titled from the
        first user message.
      - `conversation_id` present + owned by user → resumed; Anthropic gets
        the full prior {user, assistant} text history as memory.
      - `conversation_id` present + NOT owned (or unknown) → 404
        ConversationNotFound (single message — no enumeration leak).

    On Anthropic failure: HTTP 502 with
        { "error": "chat_unavailable", "detail": "...", "status": 502 }
    The API key is **never** echoed in any response or log.
    """
    user_uuid = UUID(user["id"])

    # Resolve / create the conversation. ValueError from ensure_* means
    # caller passed an id that exists for some other user (or doesn't
    # exist at all, or isn't a UUID) — same 404 message in every case.
    try:
        conv = await ensure_conversation_for_user(
            pool,
            user_id=user_uuid,
            conversation_id=body.conversation_id,
            first_message=body.message,
        )
    except ValueError:
        raise ConversationNotFound(body.conversation_id or "")

    conv_uuid = UUID(conv["id"])

    # Persist the user turn BEFORE the model call so a mid-call crash
    # still leaves a recoverable trace, and so history_for_model below
    # includes this turn at the tail.
    await persist_user_turn(pool, conv_uuid, body.message)
    history = await conversation_history_for_model(pool, conv_uuid)

    screen_payload = body.context.model_dump() if body.context else None
    screen_context = (
        body.context.current_page.value if body.context and body.context.current_page else None
    )

    try:
        result = await chat_service.generate_reply(
            history=history,
            screen_context=screen_context,
            screen_payload=screen_payload,
            conn=conn,
        )
    except chat_service.ChatUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "chat_unavailable", "detail": exc.safe_message,
                     "status": 502},
        )

    await persist_assistant_turn(
        pool, conv_uuid, result["reply"],
        data_sources_used=result["data_sources_used"] or None,
    )

    return ChatResponse(
        conversation_id=str(conv_uuid),
        reply=result["reply"],
        data_sources_used=result["data_sources_used"],
        suggested_followups=result["suggested_followups"],
        timestamp=_iso_now(),
    )


@router.get("/chat/suggested-prompts", response_model=SuggestedPrompts)
async def get_suggested_prompts(
    current_page: Optional[str] = Query(None),
    current_machine_id: Optional[str] = Query(None),
    current_sku: Optional[str] = Query(None),
) -> SuggestedPrompts:
    prompts = chat_service.suggested_prompts(
        current_page=current_page,
        current_machine_id=current_machine_id,
        current_sku=current_sku,
    )
    return SuggestedPrompts(prompts=prompts)
