"""User maintenance entries — POST/GET/DELETE on /machines/{id}/maintenance-entries.

Auth required everywhere (Phase A). DELETE is owner-only with the same
404-on-foreign-id pattern as chat_memory.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, Path, Response, status

from ..auth.dependencies import get_current_user
from ..db import get_pool
from ..errors import APIError, MachineNotFound
from ..services.constants import VALID_MACHINE_IDS
from .models import (
    MaintenanceEntry, MaintenanceEntryCreate, MaintenanceEntryListResponse,
)
from .services import (
    create_entry, delete_entry, list_entries_for_machine,
)

router = APIRouter(tags=["maintenance"])


class MaintenanceEntryNotFound(APIError):
    code = "maintenance_entry_not_found"
    status_code = 404

    def __init__(self, entry_id: str) -> None:
        super().__init__(f"No maintenance entry with ID '{entry_id}'.")


def _get_pool_dep() -> asyncpg.Pool:
    return get_pool()


def _validate_machine(machine_id: str) -> None:
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)


@router.post(
    "/machines/{machine_id}/maintenance-entries",
    response_model=MaintenanceEntry,
    status_code=status.HTTP_201_CREATED,
)
async def post_maintenance_entry(
    machine_id: str = Path(..., min_length=1),
    body: MaintenanceEntryCreate = Body(...),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> MaintenanceEntry:
    _validate_machine(machine_id)
    row = await create_entry(
        pool,
        user_id=UUID(user["id"]),
        machine_id=machine_id,
        component_id=body.component_id,
        maintenance_type=body.maintenance_type,
        work_description=body.work_description,
        technician_name=body.technician_name,
        cost_usd=body.cost_usd,
        duration_hours=body.duration_hours,
        performed_at=body.performed_at,
    )
    return MaintenanceEntry(**row)


@router.get(
    "/machines/{machine_id}/maintenance-entries",
    response_model=MaintenanceEntryListResponse,
)
async def list_maintenance_entries(
    machine_id: str = Path(..., min_length=1),
    _user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> MaintenanceEntryListResponse:
    _validate_machine(machine_id)
    rows = await list_entries_for_machine(pool, machine_id)
    return MaintenanceEntryListResponse(
        entries=[MaintenanceEntry(**r) for r in rows],
    )


@router.delete(
    "/machines/{machine_id}/maintenance-entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_maintenance_entry(
    machine_id: str = Path(..., min_length=1),
    entry_id: str = Path(..., min_length=1),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(_get_pool_dep),
) -> Response:
    _validate_machine(machine_id)
    try:
        eid = UUID(entry_id)
    except (TypeError, ValueError) as exc:
        raise MaintenanceEntryNotFound(entry_id) from exc

    deleted = await delete_entry(pool, eid, UUID(user["id"]))
    if not deleted:
        raise MaintenanceEntryNotFound(entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
