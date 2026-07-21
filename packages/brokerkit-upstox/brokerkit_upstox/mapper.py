from datetime import date, datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import (
    Exchange, InstrumentType, OrderStatus, OrderType, Product, Segment, TransactionType, Validity,
)
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain, OptionChainStrike, OptionContract, OptionGreeks
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position
from brokerkit.models.quote import Ohlc, Quote
from brokerkit.models.tick import Tick

# Verified live 2026-07-20 against the SDK's own quickstart/example code and
# rendered docs — Upstox spells SL_M with a hyphen ("SL-M"), unlike core's
# underscore. Everything else is an identical string.
_ORDER_TYPE_TO_UPSTOX = {
    OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL", OrderType.SL_M: "SL-M",
}
_ORDER_TYPE_FROM_UPSTOX = {v: k for k, v in _ORDER_TYPE_TO_UPSTOX.items()}

# core Product has no MTF/CO — deliberately excluded like Groww/Fyers exclude
# their own SDK/platform extras: "D"/"I" are the only two confirmed (from
# the SDK's own example code) values for the `product` field; MTF and CO
# exist on the Upstox platform but aren't confirmed as valid API `product`
# values anywhere — same "unverified promises, add only when tested" rule.
_PRODUCT_TO_UPSTOX = {Product.CNC: "D", Product.MIS: "I"}
_PRODUCT_FROM_UPSTOX = {v: k for k, v in _PRODUCT_TO_UPSTOX.items()}

# Upstox's order status has 17 raw values (verified against the official
# order-status appendix) — far more granular than core's 6. Several are
# genuinely ambiguous and need a judgment call, documented here rather than
# silently collapsed:
# - the four "*pending"/"*req received" states meaning "not yet live at the
#   exchange" -> core PENDING.
# - "open"/"modified"/"not modified"/"not cancelled"/"cancel pending"/
#   "modify pending"/"modify validation pending"/"trigger pending"/
#   "modify after market order req received" all describe an order that IS
#   already registered/live at the exchange (a pending modify/cancel
#   doesn't un-register it) -> core OPEN.
# - "complete" -> EXECUTED. "rejected" -> REJECTED.
# - "cancelled"/"cancelled after market order" -> CANCELLED.
_STATUS_MAP: dict[str, OrderStatus] = {
    "validation pending": OrderStatus.PENDING,
    "put order req received": OrderStatus.PENDING,
    "after market order req received": OrderStatus.PENDING,
    "open pending": OrderStatus.PENDING,
    "open": OrderStatus.OPEN,
    "modified": OrderStatus.OPEN,
    "not modified": OrderStatus.OPEN,
    "not cancelled": OrderStatus.OPEN,
    "cancel pending": OrderStatus.OPEN,
    "modify pending": OrderStatus.OPEN,
    "modify validation pending": OrderStatus.OPEN,
    "trigger pending": OrderStatus.OPEN,
    "modify after market order req received": OrderStatus.OPEN,
    "complete": OrderStatus.EXECUTED,
    "rejected": OrderStatus.REJECTED,
    "cancelled": OrderStatus.CANCELLED,
    "cancelled after market order": OrderStatus.CANCELLED,
}


def order_type_to_upstox(order_type: OrderType) -> str:
    return _ORDER_TYPE_TO_UPSTOX[order_type]


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"Unknown Upstox order status: {raw!r}") from None


def map_product(raw: str) -> Product:
    try:
        return _PRODUCT_FROM_UPSTOX[raw]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Upstox product: {raw!r}") from None


def _decimal(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def epoch_ms_dt(v: int | float | None) -> datetime | None:
    return None if not v else datetime.fromtimestamp(v / 1000)


def _segment_from_token(token: str) -> Segment:
    """"NSE_FO|51834" -> FNO. Same segment-code vocabulary UpstoxInstruments
    parses off the raw instrument master (NSE_EQ/BSE_EQ/NSE_INDEX/BSE_INDEX
    -> CASH default, NSE_FO/BSE_FO/MCX_FO -> FNO, NSE_COM -> COMMODITY).
    """
    code = token.split("|", 1)[0]
    if code.endswith("_FO"):
        return Segment.FNO
    if code.endswith("_COM"):
        return Segment.COMMODITY
    return Segment.CASH


def upstox_key(instrument: Instrument) -> str:
    """Instrument -> Upstox's own instrument_key (e.g. "NSE_EQ|INE002A01018"),
    stashed onto exchange_token by UpstoxInstruments — every Upstox call
    that needs to address an instrument uses this, never a reconstruction.
    """
    if not instrument.exchange_token:
        raise ValueError(f"Instrument {instrument.symbol!r} has no Upstox instrument_key (exchange_token)")
    return instrument.exchange_token


def order_request_to_upstox(request: OrderRequest) -> dict[str, Any]:
    return {
        "quantity": request.quantity,
        "product": _PRODUCT_TO_UPSTOX[request.product],
        "validity": request.validity.value,
        "price": float(request.price) if request.price is not None else 0,
        "instrument_token": upstox_key(request.instrument),
        "order_type": _ORDER_TYPE_TO_UPSTOX[request.order_type],
        "transaction_type": request.transaction_type.value,
        "disclosed_quantity": 0,
        "trigger_price": float(request.trigger_price) if request.trigger_price is not None else 0,
        "is_amo": False,
    }


def upstox_to_order(data: dict[str, Any]) -> Order:
    """order_data-shaped dict (get_order_book/get_order_details item) -> Order."""
    return Order(
        order_id=data["order_id"],
        status=map_status(data["status"]),
        trading_symbol=data.get("trading_symbol") or data.get("tradingsymbol") or "",
        exchange=Exchange(data["exchange"]),
        segment=_segment_from_token(data.get("instrument_token", "")),
        transaction_type=TransactionType(data["transaction_type"]),
        order_type=_ORDER_TYPE_FROM_UPSTOX[data["order_type"]],
        product=map_product(data["product"]),
        validity=Validity(data["validity"]),
        quantity=data["quantity"],
        filled_quantity=data.get("filled_quantity") or 0,
        price=_decimal(data.get("price")) or None,
        trigger_price=_decimal(data.get("trigger_price")) or None,
        average_price=_decimal(data.get("average_price")) or None,
        status_message=data.get("status_message") or None,
        created_at=None,
        updated_at=epoch_ms_dt(data.get("exchange_timestamp")),
    )


def place_response_to_order(order_id: str, request: OrderRequest) -> Order:
    """PlaceOrderV3Response.data is just {order_ids: [...]} — no echo of the
    order, same "thin response -> re-fetch for truth" idiom as Groww/Fyers.
    Assume PENDING immediately after submission.
    """
    return Order(
        order_id=order_id,
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
    )


def upstox_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data.get("trading_symbol") or data.get("tradingsymbol") or "",
        isin=data.get("isin"),
        quantity=data["quantity"],
        average_price=_decimal(data.get("average_price")) or Decimal("0"),
        pledged_quantity=data.get("collateral_quantity") or 0,
        t1_quantity=data.get("t1_quantity") or 0,
    )


def upstox_to_position(data: dict[str, Any]) -> Position:
    return Position(
        trading_symbol=data.get("trading_symbol") or data.get("tradingsymbol") or "",
        exchange=Exchange(data["exchange"]),
        segment=_segment_from_token(data.get("instrument_token", "")),
        product=map_product(data["product"]),
        quantity=data["quantity"],
        buy_quantity=(data.get("day_buy_quantity") or 0) + (data.get("overnight_buy_quantity") or 0),
        buy_price=_decimal(data.get("buy_price")),
        sell_quantity=(data.get("day_sell_quantity") or 0) + (data.get("overnight_sell_quantity") or 0),
        sell_price=_decimal(data.get("sell_price")),
        realised_pnl=_decimal(data.get("realised")),
        isin=None,  # position_data carries no ISIN (verified from SDK source)
    )


def upstox_to_ohlc(v: dict[str, Any]) -> Ohlc:
    """`v` = one entry's "live_ohlc" object from /v3/market-quote/ohlc, or
    (reused for `Tick.minute_ohlc`) one "I1" entry from the websocket
    feed's `marketOHLC.ohlc` list. "prev_ohlc" (previous session) is
    deliberately not used here; core's Ohlc has no room for two sessions
    and get_ohlc's contract (matching Groww/Fyers) is "today's OHLC so
    far". `vol` only exists on the websocket-feed shape (confirmed from
    MarketDataFeedV3.proto's OHLC message: interval/open/high/low/close/
    vol/ts) — the REST live_ohlc object has no such key, so `volume`
    correctly stays None there; protobuf int64 fields arrive as JSON
    strings after MessageToDict (same as `ltt` elsewhere), hence the
    explicit `int(...)` cast.
    """
    z = Decimal("0")
    return Ohlc(
        open=_decimal(v.get("open")) or z,
        high=_decimal(v.get("high")) or z,
        low=_decimal(v.get("low")) or z,
        close=_decimal(v.get("close")) or z,
        volume=int(v["vol"]) if v.get("vol") is not None else None,
    )


def upstox_to_quote(ltp_entry: dict[str, Any], ohlc_entry: dict[str, Any] | None) -> Quote:
    """Upstox's V3 LTP and OHLC are two separate endpoints (no single
    "full quote" call with depth/circuit-limits, unlike Groww) — get_quote()
    combines both. `ohlc_entry` may be None if the OHLC call didn't return
    a match; Quote.ohlc still needs a value, so that case falls back to
    zeros rather than failing the whole quote.
    """
    return Quote(
        last_price=_decimal(ltp_entry.get("last_price")) or Decimal("0"),
        ohlc=upstox_to_ohlc(ohlc_entry.get("live_ohlc", {})) if ohlc_entry else Ohlc(
            open=Decimal("0"), high=Decimal("0"), low=Decimal("0"), close=Decimal("0")
        ),
        volume=ltp_entry.get("volume") or 0,
    )


def upstox_to_tick(
    instrument: Instrument,
    ltpc: dict[str, Any],
    volume: int = 0,
    open_interest: float | None = None,
    minute_ohlc: dict[str, Any] | None = None,
) -> Tick:
    """LTPC{ltp, ltt, ltq, cp} from the websocket feed (verified against the
    SDK's own MarketDataFeedV3.proto) — protobuf int64 fields (ltt) come
    back as JSON strings after MessageToDict, so `ltt` is cast defensively
    regardless of whether it arrived as str or int. `volume`/`open_interest`
    come from the streaming layer's own "full" mode fields (`vtt`/`oi` on
    MarketFullFeed) — real 0/None for index instruments (IndexFullFeed has
    neither field, correctly: indices don't trade or carry OI). `minute_ohlc`
    is the "I1" entry from that same feed's `marketOHLC.ohlc` list — a
    real, server-computed, continuously-updating current-minute candle
    (confirmed live example: `{"interval": "I1", "open":..., "high":...,
    "low":..., "close":..., "vol":..., "ts":...}`), reusing `upstox_to_ohlc`'s
    same open/high/low/close shape.
    """
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        minute_ohlc=upstox_to_ohlc(minute_ohlc) if minute_ohlc else None,
        ltp=_decimal(ltpc.get("ltp")) or Decimal("0"),
        timestamp=epoch_ms_dt(int(ltpc["ltt"])) if ltpc.get("ltt") is not None else None,
        volume=volume,
        open_interest=open_interest,
    )


def upstox_to_candle(row: list) -> Candle:
    """[timestamp_iso_string, open, high, low, close, volume, open_interest]
    — verified against the official docs' example response. Timestamp is an
    ISO-8601 string with an explicit +05:30 offset, unlike Groww/Fyers'
    epoch-seconds convention.
    """
    z = Decimal("0")
    return Candle(
        timestamp=datetime.fromisoformat(row[0]),
        open=_decimal(row[1]) or z,
        high=_decimal(row[2]) or z,
        low=_decimal(row[3]) or z,
        close=_decimal(row[4]) or z,
        volume=row[5] or 0,
    )


def upstox_to_option_greeks(data: dict[str, Any] | None) -> OptionGreeks | None:
    if not data:
        return None
    # AnalyticsData has no "rho" (verified from the SDK's own model file —
    # vega/theta/gamma/delta/iv/pop only) — same capability gap Fyers has.
    return OptionGreeks(
        delta=data["delta"], gamma=data["gamma"], theta=data["theta"],
        vega=data["vega"], iv=data["iv"],
    )


def upstox_to_option_contract(
    instrument_key: str, strike: Decimal, option_type: InstrumentType,
    market_data: dict[str, Any], greeks: dict[str, Any] | None,
) -> OptionContract:
    return OptionContract(
        symbol=instrument_key,
        strike=strike,
        option_type=option_type,
        ltp=_decimal(market_data.get("ltp")) or Decimal("0"),
        open_interest=int(market_data.get("oi") or 0),
        volume=int(market_data.get("volume") or 0),
        bid_price=_decimal(market_data.get("bid_price")),
        ask_price=_decimal(market_data.get("ask_price")),
        greeks=upstox_to_option_greeks(greeks),
    )


def upstox_to_option_chain(rows: list[dict[str, Any]], underlying_symbol: str, expiry: date) -> OptionChain:
    """`rows` = the full response["data"] list from get_put_call_option_chain
    — already grouped one entry per strike (unlike Fyers' flat CE/PE array
    that needs client-side grouping), each with nested call_options/
    put_options. underlying_ltp isn't in this response at all (no
    option_type=="" underlying row like Fyers has) — left at 0 here;
    callers needing it should use get_quote() on the underlying separately.
    """
    strikes: list[OptionChainStrike] = []
    for row in rows:
        strike_price = Decimal(str(row["strike_price"]))
        call = row.get("call_options")
        put = row.get("put_options")
        call_contract = (
            upstox_to_option_contract(
                call["instrument_key"], strike_price, InstrumentType.CE,
                call.get("market_data") or {}, call.get("option_greeks"),
            )
            if call else None
        )
        put_contract = (
            upstox_to_option_contract(
                put["instrument_key"], strike_price, InstrumentType.PE,
                put.get("market_data") or {}, put.get("option_greeks"),
            )
            if put else None
        )
        strikes.append(OptionChainStrike(strike=strike_price, call=call_contract, put=put_contract))

    return OptionChain(
        underlying_symbol=underlying_symbol,
        underlying_ltp=Decimal("0"),
        expiry=expiry,
        strikes=sorted(strikes, key=lambda s: s.strike),
    )
