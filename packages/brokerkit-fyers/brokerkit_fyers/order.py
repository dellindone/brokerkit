import asyncio
from decimal import Decimal

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_fyers.errors import check
from brokerkit_fyers.mapper import (
    fyers_to_order,
    order_request_to_fyers,
    order_type_to_fyers,
    place_response_to_order,
)


class FyersOrderProvider(OrderProvider):
    def __init__(self, client: FyersModel):
        self._client = client

    async def place_order(self, request: OrderRequest) -> Order:
        payload = order_request_to_fyers(request)
        resp = await asyncio.to_thread(self._client.place_order, data=payload)
        check(resp, OrderError)
        return place_response_to_order(resp, request)

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
        # Unlike Groww, Fyers' modify_order only needs the fields actually
        # changing — no need to pre-fetch and fill in the unspecified ones
        # (segment isn't used by Fyers' modify call either; it's only here
        # to satisfy the broker-agnostic ABC signature).
        payload: dict = {"id": order_id}
        if quantity is not None:
            payload["qty"] = quantity
        if order_type is not None:
            payload["type"] = order_type_to_fyers(order_type)
        if price is not None:
            payload["limitPrice"] = float(price)
        if trigger_price is not None:
            payload["stopPrice"] = float(trigger_price)
        resp = await asyncio.to_thread(self._client.modify_order, data=payload)
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def cancel(self, order_id: str, segment: Segment) -> Order:
        resp = await asyncio.to_thread(self._client.cancel_order, data={"id": order_id})
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def get_order(self, order_id: str, segment: Segment) -> Order:
        # No single-order endpoint — the SDK's own get_orders() fetches the
        # whole orderbook and filters client-side (verified in fyersModel.py).
        resp = await asyncio.to_thread(self._client.get_orders, data={"id": order_id})
        check(resp, OrderError)
        matches = resp.get("orderBook") or []
        if not matches:
            raise OrderError(f"Fyers order {order_id!r} not found")
        return fyers_to_order(matches[0])

    async def list_orders(self) -> list[Order]:
        resp = await asyncio.to_thread(self._client.orderbook)
        check(resp, OrderError)
        return [fyers_to_order(o) for o in resp.get("orderBook") or []]
