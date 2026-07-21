import asyncio
from decimal import Decimal

from pydantic import BaseModel
from upstox_client import ApiClient, Configuration, OrderApi, OrderApiV3
from upstox_client.models import ModifyOrderRequest, MultiOrderRequest, PlaceOrderV3Request

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


class MultiOrderResult(BaseModel):
    """One entry's outcome from `place_multi_order` — Upstox's own response
    splits successes (`data: list[MultiOrderData]`) and failures
    (`errors: list[MultiOrderError]`) into two separate lists, each only
    carrying `correlation_id` to tie back to the request; this re-merges
    them into one result per input request, in input order, so the caller
    doesn't have to do that matching themselves. Upstox-only — no
    equivalent concept for Groww/Fyers, so this stays adapter-local
    instead of a core model.
    """

    correlation_id: str
    order_id: str | None = None
    error: str | None = None


class UpstoxOrderProvider(OrderProvider):
    """Needs the OAuth (not Analytics) token — Upstox's Analytics Token is
    read-only and can't place/modify/cancel. Writes use `OrderApiV3`
    (order_controller_v_3_api — no api_version header needed); reads split
    across two different-looking `OrderApi` methods, verified from source:
    `get_order_status(order_id)` is the actual single-order lookup (no
    api_version needed either, despite most `OrderApi` methods requiring
    one), while `get_order_details` (misleadingly named) returns order
    *history*, not a snapshot — not used here.

    `sandbox=True` (see `UpstoxSandboxAuth`) backs this with a sandbox
    `Configuration` instead — but only `place_order`/`place_multi_order`
    actually work there. Verified from the SDK's `sandbox_urls` allowlist:
    no order-read path is sandbox-supported at all, and `modify`/`cancel`'s
    own core `Order` return value needs fields (trading_symbol/exchange/
    transaction_type/product/...) that neither their own call signature
    nor a sandbox read-back can supply — fabricating them would be a
    guess, not data, so those two methods raise immediately in sandbox
    mode instead.

    `place_multi_order` is Upstox-exclusive (no Groww/Fyers equivalent) —
    an extra method, not part of the shared `OrderProvider` ABC, so it's
    only reachable by going through this concrete class (`broker.orders`/
    `broker.sandbox_orders`, both are `UpstoxOrderProvider`), same pattern
    as `brokerkit_upstox.get_access_token`.
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration, sandbox: bool = False):
        self._auth = auth
        self._configuration = configuration
        self._sandbox = sandbox
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

    async def place_multi_order(self, requests: list[OrderRequest]) -> list[MultiOrderResult]:
        """Places up to Upstox's own per-call limit of orders in one round
        trip — real option-selling/multi-leg strategies (buying/selling
        several strikes together) is the actual motivating case, not just
        abstraction-completeness. Partial success is normal: some legs can
        fill while others fail validation, so this never raises for a
        per-order failure — only for a transport/auth-level error that
        stops the whole batch. `correlation_id` is generated internally
        (the input list's own index, as a string) so results come back
        matched 1:1 with `requests`, in the same order — the caller never
        has to handle Upstox's own split data/errors response shape.
        """
        await self._refresh_token()
        payload = [
            MultiOrderRequest(
                **order_request_to_upstox(r),
                slice=False,
                correlation_id=str(i),
            )
            for i, r in enumerate(requests)
        ]
        # place_multi_order lives on the legacy-named `OrderApi` class
        # (self._read elsewhere) despite being a write — verified from
        # source (`order_api.py`), not a typo.
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.place_multi_order, payload)
        results: dict[str, MultiOrderResult] = {}
        for d in resp.data or []:
            results[d.correlation_id] = MultiOrderResult(correlation_id=d.correlation_id, order_id=d.order_id)
        for e in resp.errors or []:
            results[e.correlation_id] = MultiOrderResult(correlation_id=e.correlation_id, error=e.message)
        return [
            results.get(str(i)) or MultiOrderResult(correlation_id=str(i), error="No result returned by Upstox")
            for i in range(len(requests))
        ]

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
        if self._sandbox:
            raise OrderError(
                "Upstox sandbox has no order-read endpoint (verified from the SDK's own "
                "sandbox_urls allowlist: only place/modify/cancel/multi-place writes are "
                "sandboxed) — get_order isn't available here, and modify()/cancel() call this "
                "internally so they fail the same way."
            )
        await self._refresh_token()
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.get_order_status, order_id=order_id)
        if resp.data is None:
            raise OrderError(f"Upstox order {order_id!r} not found")
        return upstox_to_order(resp.data.to_dict())

    async def list_orders(self) -> list[Order]:
        if self._sandbox:
            raise OrderError(
                "Upstox sandbox has no order-read endpoint (verified from the SDK's own "
                "sandbox_urls allowlist) — list_orders isn't available here."
            )
        await self._refresh_token()
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.get_order_book, _API_VERSION)
        return [upstox_to_order(o.to_dict()) for o in resp.data or []]

    async def exit_all_positions(self, segment: str | None = None, tag: str | None = None) -> list[str]:
        """Bulk-exit all open positions (optionally filtered to one
        `segment`, e.g. "NSE_EQ"). Upstox-exclusive extra, not on the shared
        ABC (no Groww/Fyers equivalent) — same placement as place_multi_order.
        Returns the order_ids of the exit orders placed. `OrderApi.exit_positions`
        (self._read) despite being a write, verified from source."""
        await self._refresh_token()
        kwargs = {k: v for k, v in (("segment", segment), ("tag", tag)) if v is not None}
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.exit_positions, **kwargs)
        return list(resp.data.order_ids) if resp.data else []

    async def cancel_all_orders(self, segment: str | None = None, tag: str | None = None) -> list[str]:
        """Cancel all open/pending orders (AMO + regular), optionally
        filtered to one `segment`. Returns the cancelled order_ids.
        `OrderApi.cancel_multi_order`, verified from source."""
        await self._refresh_token()
        kwargs = {k: v for k, v in (("segment", segment), ("tag", tag)) if v is not None}
        with upstox_errors(OrderError):
            resp = await asyncio.to_thread(self._read.cancel_multi_order, **kwargs)
        return list(resp.data.order_ids) if resp.data else []
