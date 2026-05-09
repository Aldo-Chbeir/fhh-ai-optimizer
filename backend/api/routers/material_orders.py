from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Response, status
import asyncpg

from ..db import get_conn
from ..errors import InvalidRequest, MarketNotFound, OrderNotFound, SKUNotFound
from ..models.material_orders import (
    MaterialOrder, MaterialOrderCreate, MaterialOrderList,
    MaterialOrderStatus, MaterialOrderUpdate,
)
from ..services.constants import VALID_MARKET_IDS
from ..services.material_orders import (
    create_order, delete_order, list_orders, update_order,
)


router = APIRouter(tags=["calendar"])


async def _validate_sku(conn: asyncpg.Connection, sku: str) -> None:
    exists = await conn.fetchval("SELECT 1 FROM products WHERE sku = $1", sku)
    if not exists:
        raise SKUNotFound(sku)


def _validate_market(market: Optional[str]) -> None:
    if market is None:
        return
    if market not in VALID_MARKET_IDS:
        raise MarketNotFound(market)


@router.post(
    "/material-orders",
    response_model=MaterialOrder,
    status_code=status.HTTP_201_CREATED,
)
async def post_material_order(
    body: MaterialOrderCreate = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> MaterialOrder:
    if body.expected_arrival_date < body.order_date:
        raise InvalidRequest("expected_arrival_date must be on or after order_date.")
    await _validate_sku(conn, body.sku)
    _validate_market(body.market)
    payload = body.model_dump()
    payload["status"] = payload["status"].value
    row = await create_order(conn, payload)
    return MaterialOrder(**row)


@router.patch("/material-orders/{order_id}", response_model=MaterialOrder)
async def patch_material_order(
    order_id: str,
    body: MaterialOrderUpdate = Body(...),
    conn: asyncpg.Connection = Depends(get_conn),
) -> MaterialOrder:
    payload = body.model_dump(exclude_unset=True)
    if "sku" in payload and payload["sku"] is not None:
        await _validate_sku(conn, payload["sku"])
    if "market" in payload and payload["market"] is not None:
        _validate_market(payload["market"])
    if "status" in payload and payload["status"] is not None:
        payload["status"] = payload["status"].value
    if (
        "order_date" in payload and "expected_arrival_date" in payload
        and payload["order_date"] is not None
        and payload["expected_arrival_date"] is not None
        and payload["expected_arrival_date"] < payload["order_date"]
    ):
        raise InvalidRequest("expected_arrival_date must be on or after order_date.")
    row = await update_order(conn, order_id, payload)
    if row is None:
        raise OrderNotFound(order_id)
    return MaterialOrder(**row)


@router.delete(
    "/material-orders/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_material_order(
    order_id: str,
    conn: asyncpg.Connection = Depends(get_conn),
) -> Response:
    deleted = await delete_order(conn, order_id)
    if not deleted:
        raise OrderNotFound(order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/material-orders", response_model=MaterialOrderList)
async def get_material_orders(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    status_filter: Optional[MaterialOrderStatus] = Query(None, alias="status"),
    conn: asyncpg.Connection = Depends(get_conn),
) -> MaterialOrderList:
    if start is not None and end is not None and end < start:
        raise InvalidRequest("`end` must be on or after `start`.")
    rows = await list_orders(
        conn,
        start=start, end=end,
        status=status_filter.value if status_filter else None,
    )
    orders = [MaterialOrder(**r) for r in rows]
    return MaterialOrderList(orders=orders, total=len(orders))
