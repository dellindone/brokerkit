"""Good-Till-Triggered (GTT) orders — a Zerodha-exclusive extra.

GTT is a standing instruction that sits on Zerodha's servers (up to a year)
and fires a real order when the price crosses a trigger. It is NOT an order
type: GTTs live in their own order book with their own endpoints and
lifecycle, so they are deliberately not squeezed into the core
`OrderProvider` ABC. That matches how Dhan's Global Stocks / risk control and
Angel's analytics were placed — a genuinely new capability no other broker in
this project has gets an adapter-local provider with adapter-local models.

Every prior adapter dropped GTT-like features as YAGNI (Groww's GTT/OCO,
Fyers', Upstox's, Dhan's Forever Orders). Zerodha's is built because the user
explicitly picked it as one of this adapter's roles.

Two trigger types, mirroring Kite's own vocabulary:
  * `single`  — one trigger, one order.
  * `two-leg` — OCO (one-cancels-other): a stop-loss and a target on a
    holding; whichever fires first cancels the other. Requires exactly two
    trigger values, ascending.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from brokerkit.enums import Exchange, OrderType, Product, Segment, TransactionType
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.models.instrument import Instrument

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors

TRIGGER_SINGLE = "single"
TRIGGER_OCO = "two-leg"


class GttLeg(BaseModel):
    """One order that fires when its trigger is hit."""

    transaction_type: TransactionType
    quantity: int
    price: Decimal
    order_type: OrderType = OrderType.LIMIT
    product: Product = Product.CNC


class GttTrigger(BaseModel):
    """A GTT as Kite reports it back."""

    trigger_id: int
    trigger_type: str
    status: str
    trading_symbol: str
    exchange: Exchange
    segment: Segment
    trigger_values: list[Decimal]
    last_price: Decimal | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None


class ZerodhaGtt:
    """`broker.gtt` — adapter-local, not part of the shared Broker contract."""

    def __init__(self, client):
        self._client = client  # shared KiteConnect

    async def place(
        self,
        instrument: Instrument,
        trigger_values: list[Decimal],
        last_price: Decimal,
        legs: list[GttLeg],
        trigger_type: str = TRIGGER_SINGLE,
    ) -> int:
        """Create a GTT; returns Kite's trigger_id.

        `last_price` is the instrument's current market price — Kite requires
        it on both create and modify (it validates the trigger against the
        live price), so callers should pass a fresh `market.get_ltp()` value
        rather than a stale one.
        """
        _validate(trigger_type, trigger_values, legs)
        with zerodha_errors():
            resp = await asyncio.to_thread(
                self._client.place_gtt,
                trigger_type,
                instrument.symbol,
                mapper.to_kite_exchange(instrument),
                [float(v) for v in trigger_values],
                float(last_price),
                [_leg_payload(leg) for leg in legs],
            )
        trigger_id = (resp or {}).get("trigger_id")
        if trigger_id is None:
            raise BrokerKitError(f"Kite place_gtt returned no trigger_id: {resp!r}")
        return int(trigger_id)

    async def modify(
        self,
        trigger_id: int,
        instrument: Instrument,
        trigger_values: list[Decimal],
        last_price: Decimal,
        legs: list[GttLeg],
        trigger_type: str = TRIGGER_SINGLE,
    ) -> int:
        """Kite's GTT modify replaces the whole trigger — every field must be
        resent, there is no partial update (the Groww/Dhan/Angel "resend
        everything" shape, not Kite's own order-modify behaviour, which is
        changed-fields-only)."""
        _validate(trigger_type, trigger_values, legs)
        with zerodha_errors():
            resp = await asyncio.to_thread(
                self._client.modify_gtt,
                trigger_id,
                trigger_type,
                instrument.symbol,
                mapper.to_kite_exchange(instrument),
                [float(v) for v in trigger_values],
                float(last_price),
                [_leg_payload(leg) for leg in legs],
            )
        return int((resp or {}).get("trigger_id") or trigger_id)

    async def delete(self, trigger_id: int) -> int:
        with zerodha_errors():
            resp = await asyncio.to_thread(self._client.delete_gtt, trigger_id)
        return int((resp or {}).get("trigger_id") or trigger_id)

    async def get_trigger(self, trigger_id: int) -> GttTrigger:
        with zerodha_errors():
            raw = await asyncio.to_thread(self._client.get_gtt, trigger_id)
        if not raw:
            raise BrokerKitError(f"No GTT found with id {trigger_id}")
        return _to_trigger(raw)

    # NOT named `list`. A method called `list` shadows the builtin inside the
    # class namespace, so every `list[...]` annotation in this class (place's
    # `legs`, modify's `trigger_values`, this return type) fails to resolve
    # with "'function' object is not subscriptable". On Python 3.14 that
    # stays hidden at import time because PEP 649 defers annotation
    # evaluation — it only surfaces later, in get_type_hints, pydantic,
    # IDE tooling or anything doing runtime introspection. Found by running
    # get_type_hints over every provider class in every adapter. The name
    # also matches the OrderProvider convention (list_orders/get_order).
    async def list_triggers(self) -> list[GttTrigger]:
        with zerodha_errors():
            raw = await asyncio.to_thread(self._client.get_gtts)
        return [_to_trigger(t) for t in raw or []]


def _validate(
    trigger_type: str, trigger_values: list[Decimal], legs: list[GttLeg]
) -> None:
    """Fail here rather than letting the SDK's bare `assert` fire (which
    vanishes under `python -O`) or letting the broker reject a malformed
    payload after a network round-trip."""
    if trigger_type not in (TRIGGER_SINGLE, TRIGGER_OCO):
        raise ValueError(
            f"trigger_type must be {TRIGGER_SINGLE!r} or {TRIGGER_OCO!r}, got {trigger_type!r}"
        )
    expected = 1 if trigger_type == TRIGGER_SINGLE else 2
    if len(trigger_values) != expected:
        raise ValueError(
            f"{trigger_type} GTT needs exactly {expected} trigger value(s), "
            f"got {len(trigger_values)}"
        )
    if trigger_type == TRIGGER_OCO and trigger_values[0] >= trigger_values[1]:
        raise ValueError("OCO trigger_values must be ascending (stop-loss, then target)")
    if len(legs) != len(trigger_values):
        raise ValueError(
            f"{trigger_type} GTT needs one leg per trigger value "
            f"({len(trigger_values)}), got {len(legs)}"
        )


def _leg_payload(leg: GttLeg) -> dict[str, Any]:
    return {
        "transaction_type": leg.transaction_type.value,
        "quantity": leg.quantity,
        "price": float(leg.price),
        "order_type": mapper.order_type_to_kite(leg.order_type),
        "product": mapper.product_to_kite(leg.product),
    }


def _to_trigger(data: dict[str, Any]) -> GttTrigger:
    condition = data.get("condition") or {}
    exchange, segment = mapper.from_kite_exchange(condition.get("exchange", ""))
    return GttTrigger(
        trigger_id=int(data["id"]),
        trigger_type=data.get("type") or "",
        status=data.get("status") or "",
        trading_symbol=condition.get("tradingsymbol") or "",
        exchange=exchange,
        segment=segment,
        trigger_values=[
            Decimal(str(v)) for v in (condition.get("trigger_values") or [])
        ],
        last_price=mapper._decimal(condition.get("last_price")),
        created_at=mapper._as_ist(data.get("created_at")),
        updated_at=mapper._as_ist(data.get("updated_at")),
        expires_at=mapper._as_ist(data.get("expires_at")),
    )
