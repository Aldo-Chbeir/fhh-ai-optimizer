"""/chat conversation router — list, get, delete (auth-gated, per-user).

Note: the POST /chat endpoint itself stays in routers/chat.py because it
needs the existing tool-use plumbing. That handler now calls into this
module's services to persist each turn — see `persist_user_turn` /
`persist_assistant_turn` / `ensure_conversation_for_user`.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Response, status

from ..auth.dependencies import get_current_user
from ..db import get_pool
from ..errors import ConversationNotFound
from .models import (
    ChatMessageOut, ConversationDetailResponse, ConversationListResponse,
    ConversationSummary,
)
from .services import (
    delete_user_conversation, get_conversation_messages, get_user_conversation,
    list_user_conversations,
)

router = APIRouter(prefix="/chat", tags=["chat_memory"])


def _get_pool_dep() -> asyncpg.Pool:
    return get_pool()


def _to_uuid_or_404(raw: str) -> UUID:
    """Reject malformed UUIDs with the same 404 we use for 'not yours' so
    that conversation IDs can't be enumerated by sending random strings."""
    try:
        return UUID(raw)
    except (TypeError, ValueError) as exc:
        raise ConversationNotFound(raw) from exc


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> ConversationListResponse:
    rows = await list_user_conversations(pool, UUID(user["id"]))
    return ConversationListResponse(
        conversations=[ConversationSummary(**r) for r in rows],
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> ConversationDetailResponse:
    cid = _to_uuid_or_404(conversation_id)
    conv = await get_user_conversation(pool, cid, UUID(user["id"]))
    if conv is None:
        raise ConversationNotFound(conversation_id)
    msgs = await get_conversation_messages(pool, cid)
    return ConversationDetailResponse(
        id=conv["id"],
        title=conv["title"],
        created_at=conv["created_at"],
        messages=[
            ChatMessageOut(
                id=m["id"], role=m["role"], content=m["content"],
                data_sources_used=m["data_sources_used"],
                created_at=m["created_at"],
            )
            for m in msgs
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> Response:
    cid = _to_uuid_or_404(conversation_id)
    deleted = await delete_user_conversation(pool, cid, UUID(user["id"]))
    if not deleted:
        raise ConversationNotFound(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
