from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, Query, Response, status
import asyncpg

from ..db import get_conn
from ..errors import CalendarEventNotFound, InvalidRequest, MachineNotFound
from ..models.calendar import (
    CalendarEvent, CalendarEventCreate, CalendarEventUpdate,
    CalendarFeed, CalendarFeedItem,
)
from ..services.calendar import (
    create_event, delete_event, get_unified_feed, update_event,
)
from ..services.constants import VALID_MACHINE_IDS


router = APIRouter(tags=["calendar"])


def _validate_machine(machine_id):
    if machine_id is None:
        return
    if machine_id not in VALID_MACHINE_IDS:
        raise MachineNotFound(machine_id)


@router.post(
    "/calendar/events",
    response_model=CalendarEvent,
    status_code=status.HTTP_201_CREATED,
)
async def post_calendar_event(
    body: CalendarEventCreate = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> CalendarEvent:
    _validate_machine(body.machine_id)
    payload = body.model_dump()
    payload["event_type"] = payload["event_type"].value
    row = await create_event(conn, payload)
    return CalendarEvent(**row)


@router.patch(
    "/calendar/events/{event_id}",
    response_model=CalendarEvent,
)
async def patch_calendar_event(
    event_id: str,
    body: CalendarEventUpdate = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> CalendarEvent:
    payload = body.model_dump(exclude_unset=True)
    if "machine_id" in payload and payload["machine_id"] is not None:
        _validate_machine(payload["machine_id"])
    if "event_type" in payload and payload["event_type"] is not None:
        payload["event_type"] = payload["event_type"].value
    row = await update_event(conn, event_id, payload)
    if row is None:
        raise CalendarEventNotFound(event_id)
    return CalendarEvent(**row)


@router.delete(
    "/calendar/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_calendar_event(
    event_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> Response:
    deleted = await delete_event(conn, event_id)
    if not deleted:
        raise CalendarEventNotFound(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendar/feed", response_model=CalendarFeed)
async def get_calendar_feed(
    start: date = Query(..., description="Inclusive start (YYYY-MM-DD)"),
    end: date = Query(..., description="Inclusive end (YYYY-MM-DD)"),
) -> CalendarFeed:
    if end < start:
        raise InvalidRequest("`end` must be on or after `start`.")
    events, truncated = await get_unified_feed(start, end)
    items = [CalendarFeedItem(**e) for e in events]
    return CalendarFeed(events=items, total=len(items), truncated=truncated)
