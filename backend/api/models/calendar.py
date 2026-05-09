from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CalendarEventType(str, Enum):
    INSPECTION = "inspection"
    MEETING    = "meeting"
    TRAINING   = "training"
    AUDIT      = "audit"
    VISIT      = "visit"
    OTHER      = "other"


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    event_date: date
    event_time: Optional[time] = None
    duration_minutes: Optional[int] = Field(default=None, gt=0)
    machine_id: Optional[str] = Field(default=None, max_length=40)
    event_type: CalendarEventType
    notes: Optional[str] = Field(default=None, max_length=2000)
    created_by: Optional[str] = Field(default=None, max_length=120)


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    event_date: Optional[date] = None
    event_time: Optional[time] = None
    duration_minutes: Optional[int] = Field(default=None, gt=0)
    machine_id: Optional[str] = Field(default=None, max_length=40)
    event_type: Optional[CalendarEventType] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    created_by: Optional[str] = Field(default=None, max_length=120)


class CalendarEvent(BaseModel):
    event_id: str
    title: str
    event_date: str
    event_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    machine_id: Optional[str] = None
    event_type: CalendarEventType
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class CalendarFeedItem(BaseModel):
    """Unified-feed item. Discriminated by `source`. Optional fields are
    populated only when relevant to the source — alert rows carry severity,
    material_order rows carry sku/quantity/etc."""
    source: str
    id: str
    date: str
    title: str
    severity: Optional[str] = None
    machine_id: Optional[str] = None
    status: Optional[str] = None
    alert_id: Optional[str] = None
    technician: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    downtime_hours: Optional[float] = None
    cost_usd: Optional[float] = None
    sku: Optional[str] = None
    market: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    event_type: Optional[str] = None
    event_time: Optional[str] = None
    duration_minutes: Optional[int] = None


class CalendarFeed(BaseModel):
    events: list[CalendarFeedItem]
    total: int
    truncated: bool = False
