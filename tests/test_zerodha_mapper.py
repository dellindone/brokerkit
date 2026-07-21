from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from brokerkit.enums import InstrumentType, OrderStatus, Product

from tests.support import load_adapter_module

IST_OFFSET = timedelta(hours=5, minutes=30)


@pytest.fixture
def mapper():
    return load_adapter_module("zerodha", "mapper")


@pytest.fixture
def charges():
    # charges.py reaches kiteconnect via errors.py (installed in this env).
    return load_adapter_module("zerodha", "charges")


# Regression: kite_to_order once referenced a helper that didn't exist
# (`_order_dt` vs the real `_as_ist`), a NameError that would have crashed
# EVERY order read. This exercises the whole path on a realistic order-book
# entry and asserts the timestamps come out IST-aware.
def test_zerodha_kite_to_order_on_real_orderbook_entry(mapper):
    order = mapper.kite_to_order(
        {
            "order_id": "250721000000001",
            "exchange": "NSE",
            "tradingsymbol": "INFY",
            "status": "COMPLETE",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "product": "CNC",
            "validity": "DAY",
            "quantity": 1,
            "filled_quantity": 1,
            "price": 1500.0,
            "trigger_price": 0,
            "average_price": 1499.75,
            "status_message": None,
            # Kite hands these over as naive datetimes (machine-local); the
            # mapper must stamp them IST rather than inherit the host tz.
            "order_timestamp": datetime(2026, 7, 21, 9, 20, 0),
            "exchange_update_timestamp": datetime(2026, 7, 21, 9, 20, 5),
        }
    )
    assert order.status is OrderStatus.EXECUTED
    assert order.average_price == Decimal("1499.75")
    assert order.created_at is not None and order.created_at.utcoffset() == IST_OFFSET
    assert order.updated_at is not None and order.updated_at.utcoffset() == IST_OFFSET


# Regression: BO was nearly omitted (belief that Zerodha had discontinued it),
# but a live `profile` advertised products ["CNC","NRML","MIS","BO","CO"]. Any
# unmapped one would raise mid-list and crash list_orders. Every advertised
# value must map.
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("CNC", Product.CNC),
        ("NRML", Product.NRML),
        ("MIS", Product.MIS),
        ("BO", Product.MIS),  # bracket -> nearest intraday
        ("CO", Product.MIS),  # cover -> nearest intraday
    ],
)
def test_zerodha_maps_every_profile_advertised_product(mapper, raw, expected):
    assert mapper.map_product(raw) is expected


def test_zerodha_rejects_unknown_product(mapper):
    with pytest.raises(ValueError, match="Unknown/unsupported Kite product"):
        mapper.map_product("XYZ")


def test_zerodha_rejects_unknown_status(mapper):
    with pytest.raises(ValueError, match="Unknown Kite order status"):
        mapper.map_status("TEXTING")


def test_zerodha_portfolio_odd_keys_and_no_position_isin(mapper):
    holding = mapper.kite_to_holding(
        {
            "tradingsymbol": "RELIANCE",
            "isin": "INE002A01018",
            "quantity": 10,
            "average_price": 1400.5,
            "collateral_quantity": 4,  # -> pledged_quantity
            "t1_quantity": 2,
        }
    )
    assert holding.pledged_quantity == 4
    assert holding.isin == "INE002A01018"

    position = mapper.kite_to_position(
        {
            "tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC",
            "quantity": 5, "buy_quantity": 8, "buy_price": 1400,
            "sell_quantity": 3, "sell_price": 1410, "realised": 30,
        }
    )
    assert position.buy_quantity == 8
    assert position.isin is None  # Kite positions carry no ISIN


# Kite's master is already in RUPEES (unlike Angel/Dhan/Upstox) — tick_size and
# strike must NOT be divided, and the "0" non-option strike becomes None.
def test_zerodha_master_row_is_already_in_rupees(mapper):
    option = mapper.parse_master_row(
        {
            "instrument_token": "12345678",
            "exchange_token": "57336",
            "tradingsymbol": "NIFTY26JUL24000CE",
            "name": "NIFTY",
            "expiry": "2026-07-26",
            "strike": "24000",
            "tick_size": "0.05",
            "lot_size": "50",
            "instrument_type": "CE",
            "segment": "NFO-OPT",
            "exchange": "NFO",
        }
    )
    assert option is not None
    assert option.tick_size == Decimal("0.05")  # not /100
    assert option.strike == Decimal("24000")  # not /100
    assert option.instrument_type is InstrumentType.CE

    equity = mapper.parse_master_row(
        {
            "exchange_token": "2885",
            "tradingsymbol": "RELIANCE",
            "name": "RELIANCE",
            "expiry": "",
            "strike": "0",  # non-option placeholder
            "tick_size": "0.05",
            "lot_size": "1",
            "instrument_type": "EQ",
            "segment": "NSE",
            "exchange": "NSE",
        }
    )
    assert equity is not None
    assert equity.strike is None


# Regression: depth padding rows (Rs 0 / 0 qty) are dropped so bid/ask never
# surface a Rs 0 price — the concrete bug that cost the Angel adapter an ask.
def test_zerodha_depth_drops_padding_rows(mapper):
    levels = mapper._depth(
        [
            {"price": 1400.0, "quantity": 10, "orders": 1},
            {"price": 0, "quantity": 0, "orders": 0},  # padding
        ]
    )
    assert len(levels) == 1
    assert levels[0].price == Decimal("1400.0")


# Regression: open interest is meaningless for cash; Kite returns oi 0 there.
def test_zerodha_open_interest_nulled_for_cash(mapper, cash_instrument, option_instrument):
    assert mapper._oi(0, cash_instrument) is None
    assert mapper._oi(12345, option_instrument) == 12345.0


# Regression: the Angel charges parser silently produced zeros because the real
# labels differed from every guess. This asserts the parser reads the right
# keys by reconciling the itemised parts back to the reported total.
def test_zerodha_charges_reconcile_to_total(charges):
    entry = {
        "charges": {
            "total": 30.7,
            "brokerage": 20.0,
            "transaction_tax": 5.0,  # stt
            "transaction_tax_type": "stt",
            "exchange_turnover_charge": 3.0,
            "sebi_turnover_charge": 0.1,
            "stamp_duty": 1.5,
            "gst": {"total": 1.1},
        }
    }
    parsed = charges._to_brokerage_charges(entry)
    itemised = (
        parsed.brokerage
        + parsed.taxes.stt
        + parsed.taxes.gst
        + parsed.taxes.stamp_duty
        + parsed.other_charges.transaction
        + parsed.other_charges.sebi_turnover
    )
    assert parsed.total == Decimal("30.7")
    assert itemised == parsed.total  # no label read as a silent zero
    assert parsed.brokerage == Decimal("20.0")
