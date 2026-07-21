from decimal import Decimal

import pytest

from brokerkit.enums import OrderStatus, OrderType, Product, TransactionType
from brokerkit.models.order import OrderRequest

from tests.support import load_adapter_module


@pytest.fixture
def mapper():
    return load_adapter_module("fyers", "mapper")


def test_fyers_order_payload_and_order_mapping(mapper, cash_instrument):
    request = OrderRequest(
        instrument=cash_instrument,
        transaction_type=TransactionType.SELL,
        order_type=OrderType.SL,
        quantity=3,
        product=Product.MIS,
        price=Decimal("1401"),
        trigger_price=Decimal("1400"),
    )
    payload = mapper.order_request_to_fyers(request)
    assert payload["symbol"] == "NSE:RELIANCE"
    assert payload["type"] == 4
    assert payload["side"] == -1
    assert payload["productType"] == "INTRADAY"

    order = mapper.fyers_to_order(
        {
            "id": "fy-1", "status": 6, "symbol": "NSE:RELIANCE", "segment": 10,
            "side": -1, "type": 4, "productType": "INTRADAY", "orderValidity": "DAY",
            "qty": 3, "filledQty": 1, "limitPrice": 1401, "stopPrice": 1400,
            "tradedPrice": 1400.5,
        }
    )
    assert order.status is OrderStatus.OPEN
    assert order.exchange.value == "NSE"
    assert order.average_price == Decimal("1400.5")


def test_fyers_quote_tick_and_candle_mapping(mapper, cash_instrument):
    quote = mapper.fyers_to_quote(
        {"lp": 1400, "open_price": 1390, "high_price": 1410, "low_price": 1380,
         "prev_close_price": 1395, "volume": 10, "bid": 1399.5, "ask": 1400.5}
    )
    tick = mapper.fyers_to_tick(cash_instrument, {"ltp": 1400.25, "vol_traded_today": "11"})
    candle = mapper.fyers_to_candle([1_752_000_000, 1, 2, 0.5, 1.5, 7])
    assert quote.ohlc.close == Decimal("1395")
    assert tick.volume == 11
    assert candle.close == Decimal("1.5")


@pytest.mark.parametrize("raw, expected", [(4, OrderStatus.PENDING), (6, OrderStatus.OPEN), (2, OrderStatus.EXECUTED)])
def test_fyers_status_map(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_fyers_rejects_unknown_product(mapper):
    with pytest.raises(ValueError, match="unsupported Fyers"):
        mapper.map_product("MTF")
