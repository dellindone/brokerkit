from datetime import date
from decimal import Decimal

import pytest

from brokerkit.enums import OrderStatus, OrderType, Product, TransactionType
from brokerkit.models.order import OrderRequest

from tests.support import load_adapter_module


@pytest.fixture
def mapper():
    return load_adapter_module("groww", "mapper")


def test_groww_order_request_and_response_round_trip(mapper, cash_instrument):
    request = OrderRequest(
        instrument=cash_instrument,
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=2,
        product=Product.CNC,
        price=Decimal("1400.50"),
    )

    payload = mapper.order_request_to_groww(request)
    assert payload == {
        "trading_symbol": "RELIANCE",
        "exchange": "NSE",
        "segment": "CASH",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "product": "CNC",
        "validity": "DAY",
        "quantity": 2,
        "price": 1400.5,
    }

    order = mapper.groww_to_order(
        {
            "groww_order_id": "order-1",
            "order_status": "EXECUTED",
            "trading_symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "CASH",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "product": "CNC",
            "validity": "DAY",
            "quantity": 2,
            "filled_quantity": 2,
            "price": 1400.5,
            "average_fill_price": 1400.25,
        }
    )
    assert order.status is OrderStatus.EXECUTED
    assert order.average_price == Decimal("1400.25")


def test_groww_quote_and_option_chain_normalize_decimal_values(mapper, cash_instrument):
    quote = mapper.groww_to_quote(
        {
            "last_price": "1400.25",
            "ohlc": {"open": 1390, "high": 1410, "low": 1385, "close": 1395},
            "volume": 42,
            "depth": {"buy": [{"price": 1400, "quantity": 10}], "sell": []},
        }
    )
    assert quote.last_price == Decimal("1400.25")
    assert quote.buy_depth[0].price == Decimal("1400")

    chain = mapper.groww_to_option_chain(
        {
            "underlying_ltp": "24000",
            "strikes": {
                "24100": {"ce": {"trading_symbol": "CE", "ltp": 10}},
                "24000": {"pe": {"trading_symbol": "PE", "ltp": 9}},
            },
        },
        "NIFTY",
        date(2026, 7, 30),
    )
    assert [strike.strike for strike in chain.strikes] == [Decimal("24000"), Decimal("24100")]
    assert chain.strikes[0].put.symbol == "PE"


# Regression: Groww names the position sides debit/credit (not buy/sell) and
# stashes ISIN under symbol_isin — a wrong key here silently zeros the field.
def test_groww_portfolio_maps_debit_credit_and_odd_keys(mapper):
    holding = mapper.groww_to_holding(
        {
            "trading_symbol": "RELIANCE",
            "isin": "INE002A01018",
            "quantity": 10,
            "average_price": "1400.5",
            "pledge_quantity": 4,  # not "pledged_quantity"
            "t1_quantity": 2,
        }
    )
    assert holding.pledged_quantity == 4
    assert holding.average_price == Decimal("1400.5")

    position = mapper.groww_to_position(
        {
            "trading_symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "CASH",
            "product": "CNC",
            "quantity": 5,
            "debit_quantity": 8,  # buy side
            "debit_price": "1400",
            "credit_quantity": 3,  # sell side
            "credit_price": "1410",
            "realised_pnl": "30",
            "symbol_isin": "INE002A01018",  # not "isin"
        }
    )
    assert position.buy_quantity == 8
    assert position.sell_quantity == 3
    assert position.isin == "INE002A01018"


@pytest.mark.parametrize("raw, expected", [("OPEN", OrderStatus.OPEN), ("CANCELLED", OrderStatus.CANCELLED)])
def test_groww_status_map_is_explicit(mapper, raw, expected):
    assert mapper.map_status(raw) is expected


def test_groww_rejects_unknown_status(mapper):
    with pytest.raises(ValueError, match="Unknown Groww"):
        mapper.map_status("SURPRISE")
