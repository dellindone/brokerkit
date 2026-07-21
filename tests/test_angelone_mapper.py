from datetime import timedelta
from decimal import Decimal

import pytest

from brokerkit.enums import InstrumentType, OrderStatus, OrderType, Product, TransactionType
from brokerkit.models.order import OrderRequest

from tests.support import load_adapter_module

IST_OFFSET = timedelta(hours=5, minutes=30)


@pytest.fixture
def mapper():
    return load_adapter_module("angelone", "mapper")


@pytest.fixture
def market():
    # market.py reaches SmartApi via errors.py — the conftest stub covers it.
    return load_adapter_module("angelone", "market")


def test_angel_order_payload_and_order_mapping(mapper, cash_instrument):
    request = OrderRequest(
        instrument=cash_instrument,
        transaction_type=TransactionType.SELL,
        order_type=OrderType.SL,
        quantity=2,
        product=Product.CNC,
        price=Decimal("1401"),
        trigger_price=Decimal("1400"),
    )
    payload = mapper.order_request_to_angel(request)
    assert payload["variety"] == "STOPLOSS"  # SL/SL-M ride a separate variety axis
    assert payload["ordertype"] == "STOPLOSS_LIMIT"
    assert payload["producttype"] == "DELIVERY"  # CNC -> DELIVERY
    assert payload["quantity"] == "2"  # Angel wants strings for numerics

    order = mapper.angel_to_order(
        {
            "orderid": "an-1",
            "status": "complete",
            "tradingsymbol": "RELIANCE",
            "exchange": "NSE",
            "transactiontype": "SELL",
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": "DELIVERY",
            "duration": "DAY",
            "quantity": "2",
            "filledshares": "2",
            "price": "1401",
            "triggerprice": "1400",
            "averageprice": "1400.75",
            "updatetime": "21-Jul-2026 09:20:00",
        }
    )
    assert order.status is OrderStatus.EXECUTED
    assert order.average_price == Decimal("1400.75")
    # Angel order timestamps are IST strings; the mapper must stamp them IST.
    assert order.created_at is not None and order.created_at.utcoffset() == IST_OFFSET


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("open", OrderStatus.OPEN),
        ("trigger pending", OrderStatus.OPEN),
        ("open pending", OrderStatus.PENDING),
        ("complete", OrderStatus.EXECUTED),
        ("rejected", OrderStatus.REJECTED),
    ],
)
def test_angel_status_map(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_angel_rejects_unknown_status(mapper):
    with pytest.raises(ValueError, match="Unknown Angel order status"):
        mapper.map_status("floating")


def test_angel_portfolio_odd_keys_and_no_position_isin(mapper):
    holding = mapper.angel_to_holding(
        {
            "tradingsymbol": "RELIANCE",
            "isin": "INE002A01018",
            "quantity": "10",
            "averageprice": "1400.5",
            "collateralquantity": "4",  # -> pledged_quantity
            "t1quantity": "2",
        }
    )
    assert holding.pledged_quantity == 4
    assert holding.average_price == Decimal("1400.5")

    position = mapper.angel_to_position(
        {
            "tradingsymbol": "RELIANCE", "exchange": "NSE", "producttype": "DELIVERY",
            "netqty": "5", "buyqty": "8", "buyavgprice": "1400",
            "sellqty": "3", "sellavgprice": "1410", "realised": "30",
        }
    )
    assert position.buy_quantity == 8
    assert position.isin is None  # positions response carries no ISIN


# Regression: Angel's master `strike` AND `tick_size` are both in PAISE (÷100).
def test_angel_master_row_divides_paise(mapper):
    inst = mapper.parse_master_row(
        {
            "exch_seg": "NFO",
            "instrumenttype": "OPTIDX",
            "symbol": "NIFTY26JUL24000CE",
            "name": "NIFTY",
            "token": "57336",
            "lotsize": "50",
            "tick_size": "5.000000",  # paise -> Rs 0.05
            "expiry": "26JUL2026",
            "strike": "2400000.000000",  # paise -> Rs 24000
        }
    )
    assert inst is not None
    assert inst.tick_size == Decimal("0.05")
    assert inst.strike == Decimal("24000")
    assert inst.instrument_type is InstrumentType.CE  # CE/PE from symbol suffix


def test_angel_feed_tick_divides_paise_and_is_ist(mapper, cash_instrument):
    tick = mapper.feed_to_tick(
        cash_instrument,
        {
            "last_traded_price": 140025,  # paise -> Rs 1400.25
            "exchange_timestamp": 1_752_000_000_000,
            "volume_trade_for_the_day": 100,
        },
    )
    assert tick.ltp == Decimal("1400.25")
    assert tick.volume == 100
    assert tick.timestamp is not None and tick.timestamp.utcoffset() == IST_OFFSET


# Regression: Angel zero-PADS depth to 5 levels per side. Passing the padding
# through surfaced an ask_price of Rs 0 — a price no strategy should ever see.
def test_angel_quote_drops_zero_padded_depth(market):
    quote = market._node_to_quote(
        {
            "exchange": "NSE",
            "ltp": 1400.0,
            "tradeVolume": 100,
            "depth": {
                "buy": [
                    {"price": 1399.5, "quantity": 10, "orders": 1},
                    {"price": 0.0, "quantity": 0, "orders": 0},  # padding
                ],
                "sell": [{"price": 0.0, "quantity": 0, "orders": 0}],  # fully padded
            },
        }
    )
    assert quote.bid_price == Decimal("1399.5")
    assert len(quote.buy_depth) == 1  # padding dropped
    assert quote.ask_price is None  # empty side -> None, not Rs 0
    assert quote.sell_depth == []


# Regression: Angel returns a huge junk `opnInterest` for CASH instruments
# (RELIANCE-EQ came back with 268,716,500). Equities have no OI, so it's nulled
# outside the derivative exchanges.
def test_angel_quote_nulls_open_interest_for_cash(market):
    cash = market._node_to_quote({"exchange": "NSE", "ltp": 1400.0, "opnInterest": 268716500})
    fno = market._node_to_quote({"exchange": "NFO", "ltp": 100.0, "opnInterest": 45467305})
    assert cash.open_interest is None
    assert fno.open_interest == 45467305.0
