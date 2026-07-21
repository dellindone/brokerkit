"""Angel One order provider."""

import asyncio
from decimal import Decimal
from typing import Any

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_angelone.errors import angel_errors, check
from brokerkit_angelone.mapper import (
    _decimal,
    angel_to_order,
    map_order_type,
    order_request_to_angel,
    order_type_to_angel,
    place_response_to_order,
)


class AngelOrderProvider(OrderProvider):
    """Regular orders only (place/modify/cancel/get/list). GTT / robo(BO) /
    AMO varieties are out of v1 scope — same YAGNI as every other adapter's
    dropped order types.

    Angel has no order-read-by-id REST endpoint that takes the plain
    `orderid` (only `individual_order_details` by a separate *unique* order
    id), so get_order/cancel/modify all fetch the order book and filter
    client-side — same shape as the Fyers adapter. All order WRITES need the
    SEBI static-IP whitelisting like Groww/Fyers/Dhan, and Angel has no
    public order sandbox to sidestep it (unlike Upstox/Dhan).
    """

    def __init__(self, client):
        self._client = client  # shared SmartConnect

    async def place_order(self, request: OrderRequest) -> Order:
        params = order_request_to_angel(request)
        with angel_errors(OrderError):
            resp = await asyncio.to_thread(self._client.placeOrderFullResponse, params)
        data = check(resp, OrderError)
        return place_response_to_order(data, request)

    async def modify(
        self,
        order_id: str,
        segment: Segment,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> Order:
        # Angel's modifyOrder must resend every field (Groww/Dhan-style, not
        # Fyers' changed-only) AND needs the original `variety` (STOPLOSS vs
        # NORMAL) — which core Order doesn't carry — so pre-fetch the raw
        # order-book entry and backfill from it.
        raw = await self._raw_order(order_id)
        new_type = order_type if order_type is not None else map_order_type(raw["ordertype"])
        new_qty = quantity if quantity is not None else int(float(raw.get("quantity") or 0))
        new_price = price if price is not None else _decimal(raw.get("price"))
        new_trigger = trigger_price if trigger_price is not None else _decimal(raw.get("triggerprice"))

        params = {
            "variety": raw.get("variety") or "NORMAL",
            "orderid": order_id,
            "ordertype": order_type_to_angel(new_type),
            "producttype": raw["producttype"],
            "duration": raw.get("duration") or "DAY",
            "exchange": raw["exchange"],
            "tradingsymbol": raw["tradingsymbol"],
            "symboltoken": raw["symboltoken"],
            "quantity": str(new_qty),
            "price": str(new_price) if new_price is not None else "0",
            "triggerprice": str(new_trigger) if new_trigger is not None else "0",
        }
        with angel_errors(OrderError):
            resp = await asyncio.to_thread(self._client.modifyOrder, params)
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def cancel(self, order_id: str, segment: Segment) -> Order:
        raw = await self._raw_order(order_id)
        variety = raw.get("variety") or "NORMAL"
        with angel_errors(OrderError):
            resp = await asyncio.to_thread(self._client.cancelOrder, order_id, variety)
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def get_order(self, order_id: str, segment: Segment) -> Order:
        return angel_to_order(await self._raw_order(order_id))

    async def list_orders(self) -> list[Order]:
        data = await self._order_book()
        return [angel_to_order(o) for o in data]

    async def _order_book(self) -> list[dict[str, Any]]:
        with angel_errors(OrderError):
            resp = await asyncio.to_thread(self._client.orderBook)
        return check(resp, OrderError) or []

    async def _raw_order(self, order_id: str) -> dict[str, Any]:
        for order in await self._order_book():
            if str(order.get("orderid")) == str(order_id):
                return order
        raise OrderError(f"Order {order_id!r} not found in order book")
