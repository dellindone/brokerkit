from decimal import Decimal

import pytest

from brokerkit.enums import InstrumentType, OrderStatus, OrderType, Product, TransactionType
from brokerkit.models.order import OrderRequest

from tests.support import load_adapter_module


@pytest.fixture
def mapper():
    return load_adapter_module("upstox", "mapper")


@pytest.fixture
def instruments():
    return load_adapter_module("upstox", "instruments")


def test_upstox_order_payload_and_order_mapping(mapper, cash_instrument):
    # exchange_token doubles as Upstox's instrument_key — the payload keys off it.
    cash_instrument = cash_instrument.model_copy(update={"exchange_token": "NSE_EQ|INE002A01018"})
    request = OrderRequest(
        instrument=cash_instrument,
        transaction_type=TransactionType.SELL,
        order_type=OrderType.SL_M,
        quantity=5,
        product=Product.MIS,
        trigger_price=Decimal("1400"),
    )
    payload = mapper.order_request_to_upstox(request)
    assert payload["instrument_token"] == "NSE_EQ|INE002A01018"
    assert payload["product"] == "I"  # MIS -> "I"
    assert payload["order_type"] == "SL-M"  # hyphen, not core's underscore
    assert payload["trigger_price"] == 1400.0

    order = mapper.upstox_to_order(
        {
            "order_id": "up-1",
            "status": "complete",
            "trading_symbol": "RELIANCE",
            "exchange": "NSE",
            "instrument_token": "NSE_EQ|INE002A01018",
            "transaction_type": "SELL",
            "order_type": "SL-M",
            "product": "I",
            "validity": "DAY",
            "quantity": 5,
            "filled_quantity": 5,
            "trigger_price": 1400,
            "average_price": 1399.5,
            "exchange_timestamp": 1_752_000_000_000,
        }
    )
    assert order.status is OrderStatus.EXECUTED
    assert order.product is Product.MIS
    assert order.average_price == Decimal("1399.5")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("open", OrderStatus.OPEN),
        ("trigger pending", OrderStatus.OPEN),  # still live at the exchange
        ("put order req received", OrderStatus.PENDING),  # not yet at exchange
        ("complete", OrderStatus.EXECUTED),
        ("cancelled after market order", OrderStatus.CANCELLED),
    ],
)
def test_upstox_status_map_collapses_17_states(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_upstox_rejects_unknown_status(mapper):
    with pytest.raises(ValueError, match="Unknown Upstox order status"):
        mapper.map_status("teleported")


def test_upstox_rejects_unknown_product(mapper):
    with pytest.raises(ValueError, match="Unknown/unsupported Upstox product"):
        mapper.map_product("MTF")


# Regression: Upstox's master `tick_size` is in PAISE. The missing /100 shipped
# live for months (RELIANCE reported at Rs 10.0, a NIFTY option at Rs 5.0)
# before three other brokers agreeing on Rs 0.10 / Rs 0.05 settled it.
def test_upstox_master_tick_size_is_divided_from_paise(instruments):
    inst = instruments._parse_row(
        {
            "segment": "NSE_FO",
            "exchange": "NSE",
            "instrument_type": "CE",
            "trading_symbol": "NIFTY 26 JUL 24000 CE",
            "name": "NIFTY",
            "isin": None,
            "instrument_key": "NSE_FO|57336",
            "lot_size": 50,
            "tick_size": 5,  # paise
            "strike_price": 24000,
            "expiry": 1_753_000_000_000,
            "underlying_symbol": "NIFTY",
        }
    )
    assert inst is not None
    assert inst.tick_size == Decimal("0.05")
    assert inst.instrument_type is InstrumentType.CE
    # Upstox's strike is already in rupees (unlike Angel's paise) — not divided.
    assert inst.strike == Decimal("24000")
