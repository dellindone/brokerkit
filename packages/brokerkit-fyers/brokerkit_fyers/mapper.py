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
from brokerkit.models.quote import Ohlc, Quote
from brokerkit.models.tick import Tick

# Fyers order `type` — verified against fyersModel.place_order's docstring
# (1 Limit, 2 Market, 3 Stop/SL-M, 4 Stoplimit/SL-L). Core's SL is a
# stop-*limit* order (needs both price+trigger_price) so it's Fyers' 4;
# core's SL_M is stop-market (trigger_price only) so it's Fyers' 3.
_ORDER_TYPE_TO_FYERS = {
    OrderType.LIMIT: 1,
    OrderType.MARKET: 2,
    OrderType.SL_M: 3,
    OrderType.SL: 4,
}
_ORDER_TYPE_FROM_FYERS = {v: k for k, v in _ORDER_TYPE_TO_FYERS.items()}

_SIDE_TO_FYERS = {TransactionType.BUY: 1, TransactionType.SELL: -1}
_SIDE_FROM_FYERS = {v: k for k, v in _SIDE_TO_FYERS.items()}

# core Product has no CO/BO/MTF — deliberately excluded like Groww excluded
# its own SDK extras (BO/CO/MTF/ARB): unverified in this framework, add
# only when actually implemented+tested.
_PRODUCT_TO_FYERS = {Product.CNC: "CNC", Product.MIS: "INTRADAY", Product.NRML: "MARGIN"}
_PRODUCT_FROM_FYERS = {v: k for k, v in _PRODUCT_TO_FYERS.items()}

# Fyers status codes (verified: no status 3 exists). Fyers' own naming is
# misleading relative to core's OPEN/PENDING split: Fyers "Pending"(6) means
# the order is live/working at the exchange (core OPEN); Fyers "Transit"(4)
# means it's still on its way to the exchange, not yet confirmed (core
# PENDING). "Expired"(7) has no exact canonical match — FAILED is the
# closest fit (order didn't survive to execution).
_STATUS_MAP: dict[int, OrderStatus] = {
    1: OrderStatus.CANCELLED,
    2: OrderStatus.EXECUTED,
    4: OrderStatus.PENDING,
    5: OrderStatus.REJECTED,
    6: OrderStatus.OPEN,
    7: OrderStatus.FAILED,
}

# Verified from live symbol-master CSVs (NSE_CM/NSE_FO/BSE_CM/BSE_FO/MCX_COM):
# the `exchange` column values, used on orderbook/position responses too.
_EXCHANGE_CODE = {10: Exchange.NSE, 12: Exchange.BSE, 11: Exchange.MCX}
# the `segment` column values.
_SEGMENT_CODE = {10: Segment.CASH, 11: Segment.FNO, 20: Segment.COMMODITY}


def order_type_to_fyers(order_type: OrderType) -> int:
    return _ORDER_TYPE_TO_FYERS[order_type]


def map_status(raw: int) -> OrderStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"Unknown Fyers order status: {raw!r}") from None


def map_product(raw: str) -> Product:
    try:
        return _PRODUCT_FROM_FYERS[raw]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Fyers productType: {raw!r}") from None


def _decimal(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _epoch_dt(v: int | float | None) -> datetime | None:
    return None if not v else datetime.fromtimestamp(int(v))


def _split_symbol(full: str) -> tuple[Exchange, str]:
    """"NSE:RELIANCE-EQ" -> (Exchange.NSE, "RELIANCE-EQ")."""
    exchange, _, symbol = full.partition(":")
    return Exchange(exchange), symbol


def fyers_symbol(instrument: Instrument) -> str:
    """Instrument -> the "EXCHANGE:SYMBOL" string every Fyers call needs."""
    return f"{instrument.exchange.value}:{instrument.symbol}"


def order_request_to_fyers(request: OrderRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": fyers_symbol(request.instrument),
        "qty": request.quantity,
        "type": _ORDER_TYPE_TO_FYERS[request.order_type],
        "side": _SIDE_TO_FYERS[request.transaction_type],
        "productType": _PRODUCT_TO_FYERS[request.product],
        "validity": request.validity.value,
        "limitPrice": float(request.price) if request.price is not None else 0,
        "stopPrice": float(request.trigger_price) if request.trigger_price is not None else 0,
        "disclosedQty": 0,
        "offlineOrder": False,
    }
    return payload


def fyers_to_order(data: dict[str, Any]) -> Order:
    """orderbook() item -> Order. `symbol` carries exchange as a prefix;
    `segment` is the numeric code (verified against live CSVs)."""
    exchange, trading_symbol = _split_symbol(data["symbol"])
    return Order(
        order_id=data["id"],
        status=map_status(data["status"]),
        trading_symbol=trading_symbol,
        exchange=exchange,
        segment=_SEGMENT_CODE[data["segment"]],
        transaction_type=_SIDE_FROM_FYERS[data["side"]],
        order_type=_ORDER_TYPE_FROM_FYERS[data["type"]],
        product=map_product(data["productType"]),
        validity=Validity(data["orderValidity"]),
        quantity=data["qty"],
        filled_quantity=data.get("filledQty") or 0,
        price=_decimal(data.get("limitPrice")) or None,
        trigger_price=_decimal(data.get("stopPrice")) or None,
        average_price=_decimal(data.get("tradedPrice")) or None,
        status_message=data.get("message") or None,
        updated_at=None,  # orderDateTime format not verified precisely enough to parse confidently
    )


def place_response_to_order(data: dict[str, Any], request: OrderRequest) -> Order:
    """place_order's response is just {s, code, message, id} — no status,
    no echo of the order. Assume PENDING (order accepted, in transit —
    Fyers' own "Transit" wording) immediately after submission; callers
    that need the authoritative state should re-fetch via get_order(),
    same "thin response -> re-fetch for truth" idiom as Groww's adapter.
    """
    return Order(
        order_id=data["id"],
        status=OrderStatus.PENDING,
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
        status_message=data.get("message"),
    )


def fyers_to_holding(data: dict[str, Any]) -> Holding:
    _, trading_symbol = _split_symbol(data["symbol"])
    return Holding(
        trading_symbol=trading_symbol,
        isin=None,  # Fyers holdings response doesn't carry ISIN
        quantity=data["quantity"],
        average_price=_decimal(data.get("costPrice")) or Decimal("0"),
        pledged_quantity=data.get("collateralQuantity") or 0,
        t1_quantity=data.get("qty_t1") or 0,
    )


def fyers_to_position(data: dict[str, Any]) -> Position:
    exchange, trading_symbol = _split_symbol(data["symbol"])
    return Position(
        trading_symbol=trading_symbol,
        exchange=exchange,
        segment=_SEGMENT_CODE[data["segment"]],
        product=map_product(data["productType"]),
        quantity=data["netQty"],
        buy_quantity=data.get("buyQty") or 0,
        buy_price=_decimal(data.get("buyAvg")),
        sell_quantity=data.get("sellQty") or 0,
        sell_price=_decimal(data.get("sellAvg")),
        realised_pnl=_decimal(data.get("realized_profit")),
        isin=None,
    )


def fyers_to_ohlc(v: dict[str, Any]) -> Ohlc:
    z = Decimal("0")
    return Ohlc(
        open=_decimal(v.get("open_price")) or z,
        high=_decimal(v.get("high_price")) or z,
        low=_decimal(v.get("low_price")) or z,
        # Fyers' /quotes has no live "close" during market hours — prev_close_price
        # is the closest available field (same convention brokers commonly use here).
        close=_decimal(v.get("prev_close_price")) or z,
    )


def fyers_to_quote(v: dict[str, Any]) -> Quote:
    """`v` = the per-symbol object under response["d"][i]["v"] from /quotes.
    Note /quotes has no depth/circuit-limit fields — those only exist on
    /depth, which get_quote() doesn't call (see market.py); this Quote will
    be narrower than Groww's equivalent, that's a real capability
    difference between the two brokers' endpoints, not an adapter bug.
    """
    return Quote(
        last_price=_decimal(v.get("lp")) or Decimal("0"),
        ohlc=fyers_to_ohlc(v),
        volume=v.get("volume") or 0,
        day_change=_decimal(v.get("ch")),
        day_change_perc=v.get("chp"),
        bid_price=_decimal(v.get("bid")),
        ask_price=_decimal(v.get("ask")),
        last_trade_time=_epoch_dt(v.get("tt")),
    )


def fyers_to_tick(instrument: Instrument, data: dict[str, Any]) -> Tick:
    """FyersDataSocket's "scrips" callback payload (field names verified
    against the SDK's own shipped map.json). Note: the SDK explicitly pops
    "OI" out of this payload before dispatching (verified in data_ws.py's
    __response_output) — open_interest is genuinely unavailable from the
    LTP feed, not a mapping gap on our side.
    """
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        ltp=_decimal(data.get("ltp")) or Decimal("0"),
        timestamp=_epoch_dt(data.get("last_traded_time") or data.get("exch_feed_time")),
        volume=int(data.get("vol_traded_today") or 0),
        open_interest=None,
    )


def fyers_to_candle(row: list) -> Candle:
    # [epoch_seconds, open, high, low, close, volume] — verified against a
    # real /history response pasted in a Fyers community thread.
    z = Decimal("0")
    return Candle(
        timestamp=datetime.fromtimestamp(row[0]),
        open=_decimal(row[1]) or z,
        high=_decimal(row[2]) or z,
        low=_decimal(row[3]) or z,
        close=_decimal(row[4]) or z,
        volume=row[5] or 0,
    )


def fyers_to_option_greeks(data: dict[str, Any] | None) -> OptionGreeks | None:
    if not data:
        return None
    # Verified live 2026-07-20: Fyers' greeks object has no "rho" key
    # (unlike Groww's, which does) — genuine capability difference.
    return OptionGreeks(
        delta=data["delta"], gamma=data["gamma"], theta=data["theta"],
        vega=data["vega"], iv=data["iv"],
    )


def fyers_to_option_contract(data: dict[str, Any]) -> OptionContract:
    _, symbol = _split_symbol(data["symbol"])
    return OptionContract(
        symbol=symbol,
        strike=Decimal(str(data["strike_price"])),
        option_type=InstrumentType(data["option_type"]),
        ltp=_decimal(data.get("ltp")) or Decimal("0"),
        open_interest=int(data.get("oi") or 0),
        volume=int(data.get("volume") or 0),
        bid_price=_decimal(data.get("bid")),
        ask_price=_decimal(data.get("ask")),
        greeks=fyers_to_option_greeks(data.get("greeks")),
    )


def fyers_to_option_chain(data: dict[str, Any], underlying_symbol: str, expiry: date) -> OptionChain:
    """`data` = response["data"] from optionchain(). The first entry in
    optionsChain is always the underlying itself (option_type == "",
    strike_price == -1) — verified live; skipped when building strikes,
    used only for underlying_ltp.
    """
    chain = data.get("optionsChain") or []
    underlying_ltp = Decimal("0")
    by_strike: dict[Decimal, dict[str, OptionContract]] = {}
    for entry in chain:
        opt_type = entry.get("option_type")
        if opt_type not in ("CE", "PE"):
            underlying_ltp = _decimal(entry.get("ltp")) or underlying_ltp
            continue
        contract = fyers_to_option_contract(entry)
        by_strike.setdefault(contract.strike, {})[opt_type] = contract

    strikes = [
        OptionChainStrike(strike=strike, call=legs.get("CE"), put=legs.get("PE"))
        for strike, legs in sorted(by_strike.items())
    ]
    return OptionChain(
        underlying_symbol=underlying_symbol,
        underlying_ltp=underlying_ltp,
        expiry=expiry,
        strikes=strikes,
    )
