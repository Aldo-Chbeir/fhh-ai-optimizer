"""Chat router — POST /chat (proxied to Anthropic), conversation get/delete,
and the cold-start suggested-prompts endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse, Response

from ..errors import ConversationNotFound
from ..models import (
    ChatRequest, ChatResponse,
    Conversation, ConversationMessage,
    SuggestedPrompts,
)
from ..services import chat as chat_service

router = APIRouter(tags=["chat"])


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/chat", response_model=ChatResponse)
async def post_chat(body: ChatRequest = Body(...)):
    """Proxy a single user turn to Anthropic.

    Request shape (per API_CONTRACT.md v1.1):
        {
          "message": str,                    # latest user turn
          "conversation_id": Optional[str],  # resume if provided
          "context": {                       # current screen state
              "current_page": ..., "current_machine_id": ..., ...
          }
        }

    Response shape:
        {
          "conversation_id", "reply",
          "data_sources_used": [...], "suggested_followups": [...],
          "timestamp"
        }

    On Anthropic failure: HTTP 502 with
        { "error": "chat_unavailable", "detail": "...", "status": 502 }
    The API key is **never** echoed in any response or log.
    """
    cid = body.conversation_id or chat_service.store.create()
    chat_service.store.append(cid, "user", body.message)

    history = chat_service.store.history_for_anthropic(cid)
    screen_payload = body.context.model_dump() if body.context else None
    screen_context = (
        body.context.current_page.value if body.context and body.context.current_page else None
    )

    try:
        result = chat_service.generate_reply(
            history=history,
            screen_context=screen_context,
            screen_payload=screen_payload,
        )
    except chat_service.ChatUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "chat_unavailable", "detail": exc.safe_message,
                     "status": 502},
        )

    chat_service.store.append(
        cid, "assistant", result["reply"],
        data_sources_used=result["data_sources_used"],
    )

    return ChatResponse(
        conversation_id=cid,
        reply=result["reply"],
        data_sources_used=result["data_sources_used"],
        suggested_followups=result["suggested_followups"],
        timestamp=_iso_now(),
    )


@router.get(
    "/chat/conversations/{conversation_id}",
    response_model=Conversation,
)
async def get_conversation(conversation_id: str) -> Conversation:
    conv = chat_service.store.get(conversation_id)
    if conv is None:
        raise ConversationNotFound(conversation_id)
    return Conversation(
        conversation_id=conv["conversation_id"],
        created_at=conv["created_at"],
        messages=[ConversationMessage(**m) for m in conv["messages"]],
    )


@router.delete(
    "/chat/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(conversation_id: str) -> Response:
    if not chat_service.store.delete(conversation_id):
        raise ConversationNotFound(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
