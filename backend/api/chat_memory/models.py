"""Pydantic schemas for /chat conversation listing + retrieval.

The POST /chat request/response models live in models/chat.py — those carry
`conversation_id` already (the existing Phase-1 contract). This module only
adds the new list + detail shapes that didn't exist before persistence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    id: str
    title: Optional[str] = None
    updated_at: datetime
    message_count: int


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    # JSONB column — list of tool names, or null when not stored
    data_sources_used: Optional[list[Any]] = None
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: datetime
    messages: list[ChatMessageOut]
