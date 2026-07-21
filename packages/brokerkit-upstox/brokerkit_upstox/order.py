import asyncio
from decimal import Decimal

from upstox_client import ApiClient, Configuration, OrderApi, OrderApiV3
from upstox_client.models import ModifyOrderRequest, PlaceOrderV3Request

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import (
    order_request_to_upstox,
    order_type_to_upstox,
    place_response_to_order,
    upstox_to_order,
)

_API_VERSION = "2.0"


class UpstoxOrderProvider(OrderProvider):
    """Needs the OAuth (not Analytics) token — Upstox's Analytics Token is
    read-only and can't place/modify/cancel. Writes use `OrderApiV3`
    (order_controller_v_3_api — no api_version header needed); reads split
    across two different-looking `OrderApi` methods, verified from source:
    `get_order_status(order_id)` is the actual single-order lookup (no
    api_version needed either, despite most `OrderApi` methods requiring
    one), while `get_order_details` (misleadingly named) returns order
    *history*, not a snapshot — not used here.
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        client = ApiClient(configuration)
        self._write = OrderApiV3(client)
        self._read = OrderApi(client)

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def place_order(self, request: OrderRequest) -> Order:
        await self._refresh_token()
        payload = PlaceOrderV3Request(**order_request_to_upstox(request))
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._write.place_order, payload)
        order_ids = resp.data.order_ids if resp.data else []
        if not order_ids:
            raise OrderError(f"Upstox place_order returned no order_ids: {resp}")
        return place_response_to_order(order_ids[0], request)

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
        # Unlike Fyers (only changed fields) but like Groww: Upstox's
        # ModifyOrderRequest model raises ValueError on construction if
        # order_type/validity/price/trigger_price are None (verified from
        # the SDK's own setters) — every field must be resent, so an
        # unspecified one is backfilled from the current order.
        await self._refresh_token()
        current = await self.get_order(order_id, segment)
        payload = ModifyOrderRequest(
            order_id=order_id,
            quantity=quantity if quantity is not None else current.quantity,
            order_type=order_type_to_upstox(order_type if order_type is not None else current.order_type),
            validity=current.validity.value,
            price=float(price if price is not None else (current.price or 0)),
            trigger_price=float(trigger_price if trigger_price is not None else (current.trigger_price or 0)),
        )
        with upstox_errors(OrderError):
            await asyncio.to_thread(self._write.modify_order, payload)
        return await self.get_order(order_id, segment)

    async def cancel(self, order_id: str, segment: Segment) -> Order:
        await self._refresh_token()
        with upstox_errors(OrderError):
            await asyncio.to_thread(self._write.cancel_order, order_id)
        return await self.get_order(order_id, segment)

    async def get_order(self, order_id: str, segment: Segment) -> Order:
        await self._refresh_token()
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.get_order_status, order_id=order_id)
        if resp.data is None:
            raise OrderError(f"Upstox order {order_id!r} not found")
        return upstox_to_order(resp.data.to_dict())

    async def list_orders(self) -> list[Order]:
        await self._refresh_token()
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.get_order_book, _API_VERSION)
        return [upstox_to_order(o.to_dict()) for o in resp.data or []]
