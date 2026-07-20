from datetime import date, datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import (
    Exchange, InstrumentType, OrderStatus, OrderType, Product, Segment, TransactionType, Validity,
)
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.option_chain import OptionChain, OptionChainStrike, OptionContract, OptionGreeks
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument
from brokerkit.models.quote import DepthLevel, Ohlc, Quote
from brokerkit.models.tick import Tick

_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.PENDING,
    "ACKED": OrderStatus.PENDING,
    "APPROVED": OrderStatus.OPEN,
    "OPEN": OrderStatus.OPEN,
    "TRIGGER_PENDING": OrderStatus.OPEN,
    "MODIFICATION_REQUESTED": OrderStatus.OPEN,
    "CANCELLATION_REQUESTED": OrderStatus.OPEN,
    "EXECUTED": OrderStatus.EXECUTED,
    "COMPLETED": OrderStatus.EXECUTED,
    "DELIVERY_AWAITED": OrderStatus.EXECUTED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "FAILED": OrderStatus.FAILED,
}


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"Unknown Groww order status: {raw!r}") from None


def _decimal(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _dt(v: str | None) -> datetime | None:
    return None if v is None else datetime.fromisoformat(v)

def _epoch_dt(v: int | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromtimestamp(v / 1000 if v > 1_000_000_000_000 else v)

def _depth_levels(rows: list | None) -> list[DepthLevel]:
    return [
        DepthLevel(price=_decimal(r["price"]) or Decimal("0"), quantity=r["quantity"])
        for r in rows or []
    ]


def order_request_to_groww(request: OrderRequest) -> dict[str, Any]:
    """OrderRequest -> place_order kwargs."""
    payload: dict[str, Any] = {
        "trading_symbol": request.instrument.symbol,
        "exchange": request.instrument.exchange.value,
        "segment": request.instrument.segment.value,
        "transaction_type": request.transaction_type.value,
        "order_type": request.order_type.value,
        "product": request.product.value,
        "validity": request.validity.value,
        "quantity": request.quantity,
    }
    if request.price is not None:
        payload["price"] = float(request.price)
    if request.trigger_price is not None:
        payload["trigger_price"] = float(request.trigger_price)
    return payload


def groww_to_order(data: dict[str, Any]) -> Order:
    """get_order_detail / get_order_list item -> Order."""
    return Order(
        order_id=data["groww_order_id"],
        status=map_status(data["order_status"]),
        trading_symbol=data["trading_symbol"],
        exchange=Exchange(data["exchange"]),
        segment=Segment(data["segment"]),
        transaction_type=TransactionType(data["transaction_type"]),
        order_type=OrderType(data["order_type"]),
        product=Product(data["product"]),
        validity=Validity(data["validity"]),
        quantity=data["quantity"],
        filled_quantity=data.get("filled_quantity") or 0,
        price=_decimal(data.get("price")),
        trigger_price=_decimal(data.get("trigger_price")),
        average_price=_decimal(data.get("average_fill_price")),
        status_message=data.get("remark"),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("exchange_time")),
    )


def place_response_to_order(data: dict[str, Any], request: OrderRequest) -> Order:
    """place_order ka thin response + original request -> Order."""
    return Order(
        order_id=data["groww_order_id"],
        status=map_status(data["order_status"]),
        trading_symbol=request.instrument.symbol,
        exchange=request.instrument.exchange,
        segment=request.instrument.segment,
        transaction_type=request.transaction_type,
        order_type=request.order_type,
        product=request.product,
        validity=request.validity,
        quantity=request.quantity,
        price=request.price,
        trigger_price=request.trigger_price,
        status_message=data.get("remark"),
    )

def groww_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data["trading_symbol"],
        isin=data.get("isin"),
        quantity=data["quantity"],
        average_price=_decimal(data["average_price"]) or Decimal("0"),
        pledged_quantity=data.get("pledge_quantity") or 0,
        t1_quantity=data.get("t1_quantity") or 0,
    )


def groww_to_position(data: dict[str, Any]) -> Position:
    # Groww: debit = buy side, credit = sell side
    return Position(
        trading_symbol=data["trading_symbol"],
        exchange=Exchange(data["exchange"]),
        segment=Segment(data["segment"]),
        product=Product(data["product"]),
        quantity=data["quantity"],
        buy_quantity=data.get("debit_quantity") or 0,
        buy_price=_decimal(data.get("debit_price")),
        sell_quantity=data.get("credit_quantity") or 0,
        sell_price=_decimal(data.get("credit_price")),
        realised_pnl=_decimal(data.get("realised_pnl")),
        isin=data.get("symbol_isin"),
    )

def groww_to_ohlc(data: dict[str, Any]) -> Ohlc:
    z = Decimal("0")
    return Ohlc(
        open=_decimal(data.get("open")) or z,
        high=_decimal(data.get("high")) or z,
        low=_decimal(data.get("low")) or z,
        close=_decimal(data.get("close")) or z,
    )

def groww_to_quote(data: dict[str, Any]) -> Quote:
    depth = data.get("depth") or {}
    return Quote(
        last_price=_decimal(data.get("last_price")) or Decimal("0"),
        ohlc=groww_to_ohlc(data.get("ohlc") or {}),
        volume=data.get("volume") or 0,
        day_change=_decimal(data.get("day_change")),
        day_change_perc=data.get("day_change_perc"),
        bid_price=_decimal(data.get("bid_price")),
        bid_quantity=data.get("bid_quantity"),
        ask_price=_decimal(data.get("offer_price")),   # offer -> ask rename
        ask_quantity=data.get("offer_quantity"),
        buy_depth=_depth_levels(depth.get("buy")),
        sell_depth=_depth_levels(depth.get("sell")),
        upper_circuit=_decimal(data.get("upper_circuit_limit")),
        lower_circuit=_decimal(data.get("lower_circuit_limit")),
        open_interest=data.get("open_interest"),
        average_price=_decimal(data.get("average_price")),
        last_trade_time=_epoch_dt(data.get("last_trade_time")),
    )


def groww_to_tick(instrument: Instrument, data: dict[str, Any]) -> Tick:
    """Feed ka StocksLivePrice dict (proto field names) -> Tick."""
    ts = data.get("tsInMillis")
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        ltp=_decimal(data.get("ltp")) or Decimal("0"),
        timestamp=_epoch_dt(int(ts)) if ts else None,
        volume=int(data.get("volume") or 0),
        open_interest=data.get("openInterest"),
    )


def groww_to_candle(row: list) -> Candle:
    # [epoch_s, open, high, low, close, volume]
    z = Decimal("0")
    return Candle(
        timestamp=datetime.fromtimestamp(row[0]),
        open=_decimal(row[1]) or z,
        high=_decimal(row[2]) or z,
        low=_decimal(row[3]) or z,
        close=_decimal(row[4]) or z,
        volume=row[5] or 0,
    )


def groww_to_option_greeks(data: dict[str, Any] | None) -> OptionGreeks | None:
    if not data:
        return None
    return OptionGreeks(
        delta=data["delta"], gamma=data["gamma"], theta=data["theta"],
        vega=data["vega"], iv=data["iv"], rho=data.get("rho"),
    )


def groww_to_option_contract(
    data: dict[str, Any], strike: Decimal, option_type: InstrumentType
) -> OptionContract:
    # bid_price/ask_price deliberately left at their None default — Groww's
    # option-chain endpoint doesn't document or (per a third-party typed
    # SDK cross-check) expose them, unlike Fyers'. Not guessed.
    return OptionContract(
        symbol=data["trading_symbol"],
        strike=strike,
        option_type=option_type,
        ltp=_decimal(data.get("ltp")) or Decimal("0"),
        open_interest=int(data.get("open_interest") or 0),
        volume=int(data.get("volume") or 0),
        greeks=groww_to_option_greeks(data.get("greeks")),
    )


def groww_to_option_chain(data: dict[str, Any], underlying_symbol: str, expiry: date) -> OptionChain:
    """`strikes` = dict keyed by strike-price string, each with "ce"/"pe"
    sub-objects (verified against a third-party typed Go SDK — Groww's
    own docs don't show the nesting explicitly)."""
    strikes: list[OptionChainStrike] = []
    for strike_str, entry in (data.get("strikes") or {}).items():
        strike = Decimal(strike_str)
        ce, pe = entry.get("ce"), entry.get("pe")
        strikes.append(OptionChainStrike(
            strike=strike,
            call=groww_to_option_contract(ce, strike, InstrumentType.CE) if ce else None,
            put=groww_to_option_contract(pe, strike, InstrumentType.PE) if pe else None,
        ))
    strikes.sort(key=lambda s: s.strike)
    return OptionChain(
        underlying_symbol=underlying_symbol,
        underlying_ltp=_decimal(data.get("underlying_ltp")) or Decimal("0"),
        expiry=expiry,
        strikes=strikes,
    )

