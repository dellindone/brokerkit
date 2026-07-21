from datetime import date
from decimal import Decimal

import pytest

from brokerkit.enums import InstrumentType, OrderStatus, OrderType, Product, TransactionType
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


def test_fyers_portfolio_odd_keys_and_no_isin(mapper):
    holding = mapper.fyers_to_holding(
        {
            "symbol": "NSE:RELIANCE",
            "quantity": 10,
            "costPrice": 1400.5,
            "collateralQuantity": 4,  # -> pledged_quantity
            "qty_t1": 2,  # -> t1_quantity
        }
    )
    assert holding.trading_symbol == "RELIANCE"
    assert holding.pledged_quantity == 4
    assert holding.t1_quantity == 2
    assert holding.isin is None  # Fyers holdings carry no ISIN

    position = mapper.fyers_to_position(
        {
            "symbol": "NSE:RELIANCE", "segment": 10, "productType": "INTRADAY",
            "netQty": 5, "buyQty": 8, "buyAvg": 1400, "sellQty": 3, "sellAvg": 1410,
            "realized_profit": 30,
        }
    )
    assert position.buy_quantity == 8
    assert position.isin is None


def test_fyers_option_chain_skips_underlying_and_omits_rho(mapper):
    chain = mapper.fyers_to_option_chain(
        {
            "optionsChain": [
                # first entry is the underlying itself (option_type "", strike -1)
                {"symbol": "NSE:NIFTY50-INDEX", "option_type": "", "strike_price": -1, "ltp": 24000},
                {"symbol": "NSE:NIFTY24100CE", "option_type": "CE", "strike_price": 24100, "ltp": 10,
                 "oi": 100, "volume": 5, "bid": 9.5, "ask": 10.5,
                 "greeks": {"delta": 0.5, "gamma": 0.01, "theta": -1.2, "vega": 3.4, "iv": 12.5}},
                {"symbol": "NSE:NIFTY24000PE", "option_type": "PE", "strike_price": 24000, "ltp": 9,
                 "oi": 80, "volume": 4, "bid": 8.5, "ask": 9.5, "greeks": None},
            ]
        },
        "NIFTY",
        date(2026, 7, 30),
    )
    assert chain.underlying_ltp == Decimal("24000")  # read off the skipped underlying row
    assert [s.strike for s in chain.strikes] == [Decimal("24000"), Decimal("24100")]  # sorted
    ce = chain.strikes[1].call
    assert ce.option_type is InstrumentType.CE
    assert ce.greeks is not None and ce.greeks.delta == 0.5
    assert ce.greeks.rho is None  # Fyers' greeks object has no rho (unlike Groww's)
    assert chain.strikes[0].put.greeks is None  # PE row had greeks: None


@pytest.mark.parametrize("raw, expected", [(4, OrderStatus.PENDING), (6, OrderStatus.OPEN), (2, OrderStatus.EXECUTED)])
def test_fyers_status_map(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_fyers_rejects_unknown_product(mapper):
    with pytest.raises(ValueError, match="unsupported Fyers"):
        mapper.map_product("MTF")
