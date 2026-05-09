from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MaterialOrderStatus(str, Enum):
    PENDING    = "pending"
    ORDERED    = "ordered"
    IN_TRANSIT = "in_transit"
    DELIVERED  = "delivered"
    CANCELLED  = "cancelled"


class MaterialOrderCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=120)
    market: Optional[str] = Field(default=None, max_length=40)
    quantity: float = Field(gt=0)
    unit: str = Field(default="units", min_length=1, max_length=40)
    order_date: date
    expected_arrival_date: date
    status: MaterialOrderStatus = MaterialOrderStatus.PENDING
    created_by: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class MaterialOrderUpdate(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=120)
    market: Optional[str] = Field(default=None, max_length=40)
    quantity: Optional[float] = Field(default=None, gt=0)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=40)
    order_date: Optional[date] = None
    expected_arrival_date: Optional[date] = None
    status: Optional[MaterialOrderStatus] = None
    created_by: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=2000)


class MaterialOrder(BaseModel):
    order_id: str
    sku: str
    market: Optional[str] = None
    quantity: float
    unit: str
    order_date: str  # ISO date
    expected_arrival_date: str  # ISO date
    status: MaterialOrderStatus
    created_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC


class MaterialOrderList(BaseModel):
    orders: list[MaterialOrder]
    total: int
