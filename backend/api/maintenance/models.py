"""Pydantic schemas for user_maintenance_entries.

Distinct from `models/alerts.py::MaintenanceLogEntry` which describes the
seeded historical `maintenance_logs` rows. These are user-attributed and
have a wider type set (incl. inspection / predictive).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

ALLOWED_TYPES = ("preventive", "corrective", "predictive", "inspection")


class MaintenanceEntryCreate(BaseModel):
    maintenance_type: str = Field(pattern=r"^(preventive|corrective|predictive|inspection)$")
    work_description: str = Field(min_length=1, max_length=10000)
    technician_name:  str = Field(min_length=1, max_length=255)
    cost_usd:         Optional[float] = Field(default=None, ge=0)
    duration_hours:   Optional[float] = Field(default=None, ge=0)
    performed_at:     Optional[datetime] = None
    component_id:     Optional[str] = Field(default=None, max_length=100)


class MaintenanceEntry(BaseModel):
    id: str
    user_id: str
    machine_id: str
    component_id: Optional[str] = None
    maintenance_type: str
    work_description: str
    cost_usd: Optional[float] = None
    duration_hours: Optional[float] = None
    technician_name: str
    performed_at: datetime
    created_at: datetime


class MaintenanceEntryListResponse(BaseModel):
    entries: list[MaintenanceEntry]
