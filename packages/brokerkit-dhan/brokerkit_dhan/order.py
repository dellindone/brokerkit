"""Dhan order provider."""

import asyncio
from decimal import Decimal

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_dhan.errors import check
from brokerkit_dhan.mapper import (
    dhan_to_order,
    order_request_to_dhan,
    order_type_to_dhan,
    place_response_to_order,
)


def _one(data) -> dict:
    """Dhan's GET /orders/{id} may return a single object or a one-element
    list depending on the endpoint — normalize. (Verified shape TBD live;
    handles both so a shape surprise doesn't crash.)"""
    if isinstance(data, list):
        if not data:
            raise OrderError("Dhan order not found")
        return data[0]
    return data


class DhanOrderProvider(OrderProvider):
    """Regular orders only (place/modify/cancel/get/list). Super Orders,
    Conditional/Multi Orders and Forever Orders are separate Dhan order
    books, deliberately out of v1 scope (same YAGNI as Groww/Fyers/Upstox's
    dropped order types).

    The same class backs both `broker.orders` (production DhanContext) and
    `broker.sandbox_orders` (a sandbox-token DhanContext whose base_url
    points at sandbox.dhan.co) — Dhan's sandbox covers order reads too
    (unlike Upstox's), so nothing here needs sandbox-specific special-casing.
    """

    def __init__(self, dhan):
        self._dhan = dhan  # dhanhq(DhanContext) facade

    async def place_order(self, request: OrderRequest) -> Order:
        kwargs = order_request_to_dhan(request)
        resp = await asyncio.to_thread(self._dhan.place_order, **kwargs)
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
        # Dhan's modify_order requires every field resent (Groww-style, not
        # Fyers' changed-only) — pre-fetch the current order and backfill
        # anything not explicitly changed. legName="" for a regular (non
        # super-order) order.
        current = await self.get_order(order_id, segment)
        new_type = order_type if order_type is not None else current.order_type
        new_qty = quantity if quantity is not None else current.quantity
        new_price = price if price is not None else current.price
        new_trigger = trigger_price if trigger_price is not None else current.trigger_price
        resp = await asyncio.to_thread(
            self._dhan.modify_order,
            order_id=order_id,
            order_type=order_type_to_dhan(new_type),
            leg_name="",
            quantity=int(new_qty),
            price=float(new_price) if new_price is not None else 0,
            trigger_price=float(new_trigger) if new_trigger is not None else 0,
            disclosed_quantity=0,
            validity=current.validity.value,
        )
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def cancel(self, order_id: str, segment: Segment) -> Order:
        resp = await asyncio.to_thread(self._dhan.cancel_order, order_id)
        check(resp, OrderError)
        return await self.get_order(order_id, segment)

    async def get_order(self, order_id: str, segment: Segment) -> Order:
        resp = await asyncio.to_thread(self._dhan.get_order_by_id, order_id)
        data = check(resp, OrderError)
        return dhan_to_order(_one(data))

    async def list_orders(self) -> list[Order]:
        resp = await asyncio.to_thread(self._dhan.get_order_list)
        data = check(resp, OrderError)
        return [dhan_to_order(o) for o in (data or [])]

    async def exit_all_positions(self) -> None:
        """Exit all open positions at market + cancel all open orders for
        the day (DELETE /positions, `Portfolio.exit_all_positions` in the
        SDK — grouped under Portfolio there, exposed here on the order
        provider next to the other bulk-order writes). 202-accepted, no
        body. Dhan-exclusive extra, not on the shared ABC. Requires the
        SEBI static IP like every order write."""
        resp = await asyncio.to_thread(self._dhan.exit_all_positions)
        check(resp, OrderError)

    async def place_multi_order(self, requests: list[OrderRequest]) -> dict:
        """Place up to 15 orders in one request (POST /alerts/multi/orders).
        **Not wrapped by dhanhq 2.3.0rc1** — the SDK only has
        margin_calculator_multi, not this — so it's called via the SDK's
        raw dhan_http. Response shape is undocumented in Dhan's API docs
        (just "Successful operation"), so the raw response `data` is
        returned as-is rather than mapped to Order objects — treat as
        unverified until live-run. Dhan-exclusive extra, not on the shared
        ABC. Endpoint lives under /alerts/ but is the direct
        (unconditional) multi-order, distinct from Place Conditional Order.
        """
        orders = []
        for i, r in enumerate(requests):
            kwargs = order_request_to_dhan(r)
            orders.append(
                {
                    "sequence": str(i + 1),
                    "transactionType": kwargs["transaction_type"],
                    "exchangeSegment": kwargs["exchange_segment"],
                    "productType": kwargs["product_type"],
                    "orderType": kwargs["order_type"],
                    "validity": kwargs["validity"],
                    "securityId": kwargs["security_id"],
                    "quantity": kwargs["quantity"],
                    "price": kwargs["price"],
                    "triggerPrice": kwargs["trigger_price"],
                }
            )
        resp = await asyncio.to_thread(self._dhan.dhan_http.post, "/alerts/multi/orders", {"orders": orders})
        return check(resp, OrderError)
