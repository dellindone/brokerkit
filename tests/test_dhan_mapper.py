from decimal import Decimal

import pytest

from brokerkit.enums import OrderStatus, OrderType, Product, TransactionType
from brokerkit.models.order import OrderRequest

from tests.support import load_adapter_module


@pytest.fixture
def mapper():
    return load_adapter_module("dhan", "mapper")


@pytest.fixture
def instruments():
    return load_adapter_module("dhan", "instruments")


def test_dhan_order_payload_and_order_mapping(mapper, cash_instrument):
    request = OrderRequest(
        instrument=cash_instrument,
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=4,
        product=Product.NRML,
        price=Decimal("1400.5"),
    )
    payload = mapper.order_request_to_dhan(request)
    assert payload["security_id"] == "2885"
    assert payload["exchange_segment"] == "NSE_EQ"
    assert payload["product_type"] == "MARGIN"  # NRML -> MARGIN
    assert payload["price"] == 1400.5

    order = mapper.dhan_to_order(
        {
            "orderId": "dh-1",
            "orderStatus": "TRADED",
            "tradingSymbol": "RELIANCE",
            "exchangeSegment": "NSE_EQ",
            "transactionType": "BUY",
            "orderType": "LIMIT",
            "productType": "MARGIN",
            "validity": "DAY",
            "quantity": 4,
            "filledQty": 4,
            "price": 1400.5,
            "averageTradedPrice": 1400.25,
            "createTime": "2026-07-21 09:20:00",
            "updateTime": "2026-07-21 09:20:05",
        }
    )
    assert order.status is OrderStatus.EXECUTED
    assert order.product is Product.NRML
    assert order.average_price == Decimal("1400.25")


# Regression: Dhan's status names are inverted from their plain meaning —
# "PENDING" is an order live/working AT the exchange (core OPEN), while
# "TRANSIT" is one that hasn't reached the exchange yet (core PENDING).
# Collapsing on the name rather than the mapping would flip both.
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("TRANSIT", OrderStatus.PENDING),
        ("PENDING", OrderStatus.OPEN),
        ("PART_TRADED", OrderStatus.OPEN),
        ("TRADED", OrderStatus.EXECUTED),
        ("EXPIRED", OrderStatus.FAILED),
    ],
)
def test_dhan_status_map_respects_inverted_names(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_dhan_rejects_unknown_status(mapper):
    with pytest.raises(ValueError, match="Unknown Dhan order status"):
        mapper.map_status("NOPE")


def test_dhan_portfolio_odd_keys_and_no_position_isin(mapper):
    holding = mapper.dhan_to_holding(
        {
            "tradingSymbol": "RELIANCE",
            "isin": "INE002A01018",
            "totalQty": 10,  # -> quantity
            "avgCostPrice": 1400.5,
            "collateralQty": 4,  # -> pledged_quantity
            "t1Qty": 2,
        }
    )
    assert holding.quantity == 10
    assert holding.pledged_quantity == 4
    assert holding.isin == "INE002A01018"

    position = mapper.dhan_to_position(
        {
            "tradingSymbol": "RELIANCE", "exchangeSegment": "NSE_EQ", "productType": "CNC",
            "netQty": 5, "buyQty": 8, "buyAvg": 1400, "sellQty": 3, "sellAvg": 1410,
            "realizedProfit": 30,
        }
    )
    assert position.buy_quantity == 8
    assert position.isin is None  # positions response carries no ISIN


def test_dhan_tick_timestamp_is_timezone_aware(mapper, cash_instrument):
    tick = mapper.dhan_to_tick(cash_instrument, {"LTP": "1400.25", "LTT": "09:20:30", "volume": 11})
    assert tick.ltp == Decimal("1400.25")
    assert tick.volume == 11
    assert tick.timestamp is not None and tick.timestamp.tzinfo is not None


# Regression: Dhan's CSV TICK_SIZE is in PAISE (÷100), same class of bug as
# Upstox's. "5.0000" is Rs 0.05, not Rs 5.
def test_dhan_master_tick_size_is_divided_from_paise(instruments):
    trading_symbols = {("NSE", "E", "2885"): "RELIANCE"}
    inst = instruments._parse_row(
        {
            "SEGMENT": "E",
            "INSTRUMENT": "EQUITY",
            "OPTION_TYPE": "",
            "EXCH_ID": "NSE",
            "SECURITY_ID": "2885",
            "ISIN": "INE002A01018",
            "SM_EXPIRY_DATE": "",
            "LOT_SIZE": "1",
            "TICK_SIZE": "5.0000",  # paise
            "SYMBOL_NAME": "RELIANCE",
            "STRIKE_PRICE": "0.00000",  # non-option placeholder
            "UNDERLYING_SYMBOL": "RELIANCE",
        },
        trading_symbols,
    )
    assert inst is not None
    assert inst.tick_size == Decimal("0.05")
    assert inst.strike is None  # "0.00000" placeholder -> None
    assert inst.isin == "INE002A01018"
