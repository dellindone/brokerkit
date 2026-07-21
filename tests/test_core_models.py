from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from brokerkit.enums import (
    Exchange,
    InstrumentType,
    OrderType,
    Product,
    Segment,
    TransactionType,
)
from brokerkit.models.auth import AuthToken
from brokerkit.models.instrument import Instrument
from brokerkit.models.order import OrderRequest
from brokerkit.utils.datetime import IST, next_occurrence


@pytest.fixture
def reliance() -> Instrument:
    return Instrument(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        segment=Segment.CASH,
        instrument_type=InstrumentType.EQ,
        exchange_token="2885",
        tick_size=Decimal("0.05"),
    )


def order_request(
    reliance: Instrument, order_type: OrderType, quantity: int = 1, **prices: Decimal
) -> OrderRequest:
    return OrderRequest(
        instrument=reliance,
        transaction_type=TransactionType.BUY,
        order_type=order_type,
        quantity=quantity,
        product=Product.CNC,
        **prices,
    )


@pytest.mark.parametrize(
    ("order_type", "prices"),
    [
        (OrderType.MARKET, {}),
        (OrderType.LIMIT, {"price": Decimal("100")} ),
        (OrderType.SL, {"price": Decimal("100"), "trigger_price": Decimal("99")} ),
        (OrderType.SL_M, {"trigger_price": Decimal("99")} ),
    ],
)
def test_order_request_accepts_valid_price_combinations(reliance, order_type, prices):
    assert order_request(reliance, order_type, **prices).order_type is order_type


@pytest.mark.parametrize(
    ("order_type", "prices"),
    [
        (OrderType.MARKET, {"price": Decimal("100")} ),
        (OrderType.MARKET, {"trigger_price": Decimal("99")} ),
        (OrderType.LIMIT, {}),
        (OrderType.LIMIT, {"price": Decimal("100"), "trigger_price": Decimal("99")} ),
        (OrderType.SL, {"price": Decimal("100")} ),
        (OrderType.SL, {"trigger_price": Decimal("99")} ),
        (OrderType.SL_M, {}),
        (OrderType.SL_M, {"price": Decimal("100"), "trigger_price": Decimal("99")} ),
    ],
)
def test_order_request_rejects_invalid_price_combinations(reliance, order_type, prices):
    with pytest.raises(ValueError):
        order_request(reliance, order_type, **prices)


def test_order_request_rejects_non_positive_quantity(reliance):
    with pytest.raises(ValueError):
        order_request(reliance, OrderType.MARKET, quantity=0)


def test_instrument_forbids_unknown_fields(reliance):
    with pytest.raises(ValueError):
        Instrument(**reliance.model_dump(), made_up="nope")


def test_auth_token_expiry_uses_safety_buffer():
    token = AuthToken(token="x", expires_at=datetime.now(IST) + timedelta(minutes=1))
    assert token.is_expired


def test_next_occurrence_keeps_today_before_target_time():
    now = datetime(2026, 7, 22, 5, 0, tzinfo=IST)
    assert next_occurrence(datetime(2026, 7, 22, 6, 0).time(), now) == datetime(
        2026, 7, 22, 6, 0, tzinfo=IST
    )


def test_next_occurrence_rolls_to_tomorrow_after_target_time():
    now = datetime(2026, 7, 22, 7, 0, tzinfo=IST)
    assert next_occurrence(datetime(2026, 7, 22, 6, 0).time(), now) == datetime(
        2026, 7, 23, 6, 0, tzinfo=IST
    )
