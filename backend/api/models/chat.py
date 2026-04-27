from __future__ import annotations

from typing import Optional, Literal

from pydantic import BaseModel, Field

from .enums import ChatPage


class ChatContext(BaseModel):
    current_page: Optional[ChatPage] = None
    current_machine_id: Optional[str] = None
    current_component_id: Optional[str] = None
    current_sku: Optional[str] = None
    current_market: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    context: Optional[ChatContext] = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    data_sources_used: list[str]
    suggested_followups: list[str]
    timestamp: str


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
    data_sources_used: Optional[list[str]] = None


class Conversation(BaseModel):
    conversation_id: str
    created_at: str
    messages: list[ConversationMessage]


class SuggestedPrompts(BaseModel):
    prompts: list[str]
