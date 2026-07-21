import asyncio
from decimal import Decimal
from typing import Any

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors


class ZerodhaOrderProvider(OrderProvider):
    """Regular orders only (place/modify/cancel/get/list).

    AMO, Cover Orders, iceberg and auction orders are Kite `variety` values
    that this adapter deliberately does not place — same YAGNI call as every
    prior adapter's dropped order types. GTT lives on `broker.gtt` instead,
    since Zerodha's GTTs are a separate order book entirely (their own
    endpoints and lifecycle), not an order-type variant.

    Two Kite-specific notes:

    * `variety` is a separate axis from `order_type` (the same shape as
      Angel's, different values) and modify/cancel both need the *existing*
      order's variety, which core `Order` doesn't carry — so both read it
      back off the order book first.
    * `modify_order` sends only the fields it is given (the SDK strips
      Nones), so `modify()` needs no pre-fetch to backfill unchanged fields —
      the Fyers behaviour, not Groww/Dhan/Angel's "resend everything".
      It still pre-fetches, but only for the variety and the return value.

    Known unverified risk on the write path: SEBI's 2026 retail-algo rules
    require market orders placed via API to carry market protection, and Kite
    exposes a `market_protection` param for it (`MARKET_PROTECTION_AUTO =
    -1`). It is deliberately NOT set here — order writes cannot be tested on
    this account (static IP, and Zerodha has no sandbox), and shipping an
    unverified parameter is a guess. If a live MARKET order is ever rejected
    for missing market protection, this is the first place to look.
    """

    def __init__(self, client):
        self._client = client  # the one shared KiteConnect

    async def place_order(self, request: OrderRequest) -> Order:
        params = mapper.order_request_to_kite(request)
        with zerodha_errors(OrderError):
            order_id = await asyncio.to_thread(self._client.place_order, **params)
        if not order_id:
            raise OrderError(f"Kite place_order returned no order_id: {order_id!r}")
        return mapper.place_response_to_order(str(order_id), request)

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
        raw = await self._raw_order(order_id)
        params: dict[str, Any] = {
            "variety": raw.get("variety") or mapper.VARIETY_REGULAR,
            "order_id": order_id,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if order_type is not None:
            params["order_type"] = mapper.order_type_to_kite(order_type)
        if price is not None:
            params["price"] = float(price)
        if trigger_price is not None:
            params["trigger_price"] = float(trigger_price)

        with zerodha_errors(OrderError):
            await asyncio.to_thread(self._client.modify_order, **params)
        # modify_order returns only the order_id, so re-read for the real
        # post-modify state (same reason Groww's adapter re-fetches).
        return await self.get_order(order_id, segment)

    async def cancel(self, order_id: str, segment: Segment) -> Order:
        raw = await self._raw_order(order_id)
        with zerodha_errors(OrderError):
            await asyncio.to_thread(
                self._client.cancel_order,
                raw.get("variety") or mapper.VARIETY_REGULAR,
                order_id,
            )
        return await self.get_order(order_id, segment)

    async def get_order(self, order_id: str, segment: Segment) -> Order:
        return mapper.kite_to_order(await self._raw_order(order_id))

    async def list_orders(self) -> list[Order]:
        with zerodha_errors(OrderError):
            raw = await asyncio.to_thread(self._client.orders)
        return [mapper.kite_to_order(o) for o in raw or []]

    async def _raw_order(self, order_id: str) -> dict[str, Any]:
        """Kite has a real single-order endpoint (`/orders/{order_id}`),
        unlike Fyers/Angel where the whole book has to be filtered. It
        returns the order's full *history* — every state transition, oldest
        first — so the last entry is the current state."""
        with zerodha_errors(OrderError):
            history = await asyncio.to_thread(self._client.order_history, order_id)
        if not history:
            raise OrderError(f"No order found with id {order_id}")
        return history[-1]
