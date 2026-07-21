"""Zerodha response-to-model mapping."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import (
    Exchange,
    InstrumentType,
    OrderStatus,
    OrderType,
    Product,
    Segment,
    TransactionType,
    Validity,
)
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position
from brokerkit.models.quote import DepthLevel, Ohlc, Quote
from brokerkit.models.tick import Tick
from brokerkit.utils.datetime import IST

# --------------------------------------------------------------------------
# Exchange / segment
# --------------------------------------------------------------------------
# Kite's `exchange` column/param strings. CDS + BCD (currency) have no core
# Segment value, and NCO (NSE commodity), GLOBAL and NSEIX (global indices)
# have no clean core (Exchange, Segment) pair either — all are dropped from
# the master, same precedent as Fyers' NSE_CD, Dhan's currency exclusion and
# Angel's CDS/NCDEX/NCO exclusion.
_TO_KITE_EXCH = {
    (Exchange.NSE, Segment.CASH): "NSE",
    (Exchange.NSE, Segment.FNO): "NFO",
    (Exchange.BSE, Segment.CASH): "BSE",
    (Exchange.BSE, Segment.FNO): "BFO",
    (Exchange.MCX, Segment.COMMODITY): "MCX",
}
_FROM_KITE_EXCH = {v: k for k, v in _TO_KITE_EXCH.items()}


def to_kite_exchange(instrument: Instrument) -> str:
    try:
        return _TO_KITE_EXCH[(instrument.exchange, instrument.segment)]
    except KeyError:
        raise ValueError(
            f"No Kite exchange for {instrument.exchange}/{instrument.segment}"
        ) from None


def from_kite_exchange(value: str) -> tuple[Exchange, Segment]:
    try:
        return _FROM_KITE_EXCH[value]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Kite exchange: {value!r}") from None


def quote_key(instrument: Instrument) -> str:
    """Kite's market-quote endpoints key everything by "EXCHANGE:TRADINGSYMBOL"
    (e.g. "NSE:INFY", "NSE:NIFTY 50") rather than by a numeric token — both
    in the request (`i=` params) and in the response dict."""
    return f"{to_kite_exchange(instrument)}:{instrument.symbol}"


# --------------------------------------------------------------------------
# The two Kite tokens
# --------------------------------------------------------------------------
# Kite's master carries TWO different identifiers per row and they are not
# interchangeable:
#   * `exchange_token`    — the real exchange-assigned token (RELIANCE 2885).
#                           This is what Angel/Fyers/Dhan also report, so it
#                           is what goes in core `Instrument.exchange_token`,
#                           keeping the cross-broker join working.
#   * `instrument_token`  — Kite's own internal id (RELIANCE 738561), and the
#                           ONLY id accepted by historical_data() and the
#                           websocket feed.
#
# They are related by  instrument_token == (exchange_token << 8) | segment_code
# where segment_code is KiteTicker.EXCHANGE_MAP's numeric segment. That is not
# an assumption — it was verified against all 122,526 rows of the real master
# (2026-07-21): 122,526 hold, 0 fail. So the adapter stores the cross-broker
# `exchange_token` and reconstructs `instrument_token` on demand below.
_SEGMENT_CODE = {
    (Exchange.NSE, Segment.CASH): 1,
    (Exchange.NSE, Segment.FNO): 2,
    (Exchange.BSE, Segment.CASH): 4,
    (Exchange.BSE, Segment.FNO): 5,
    (Exchange.MCX, Segment.COMMODITY): 7,
}
_INDICES_SEGMENT_CODE = 9  # every index row, on every exchange, uses 9


def instrument_token(instrument: Instrument) -> int:
    """Core Instrument -> Kite's internal instrument_token (historical +
    websocket). See the derivation note above — verified across the whole
    real master, not assumed."""
    if instrument.exchange_token is None:
        raise ValueError(f"{instrument.symbol} has no exchange_token")
    if instrument.instrument_type is InstrumentType.IDX:
        code = _INDICES_SEGMENT_CODE
    else:
        try:
            code = _SEGMENT_CODE[(instrument.exchange, instrument.segment)]
        except KeyError:
            raise ValueError(
                f"No Kite segment code for {instrument.exchange}/{instrument.segment}"
            ) from None
    return (int(instrument.exchange_token) << 8) | code


# --------------------------------------------------------------------------
# Instrument master
# --------------------------------------------------------------------------
# The master's `exchange` column -> (Exchange, Segment). Anything not listed
# here is dropped (CDS/BCD currency, NCO commodity, GLOBAL/NSEIX indices).
_MASTER_EXCH = {
    "NSE": (Exchange.NSE, Segment.CASH),
    "BSE": (Exchange.BSE, Segment.CASH),
    "NFO": (Exchange.NSE, Segment.FNO),
    "BFO": (Exchange.BSE, Segment.FNO),
    "MCX": (Exchange.MCX, Segment.COMMODITY),
}

# Kite's own `instrument_type` column has only four values — EQ, FUT, CE, PE
# (verified against the real master: 22,677 EQ / 1,077 FUT / 49,280 CE /
# 49,492 PE). Note there is NO index type: an index row carries
# instrument_type "EQ" and is identified only by its `segment` column being
# "INDICES". Trusting instrument_type alone would silently classify every
# index as a tradeable equity.
_INDEX_SEGMENT = "INDICES"
_INSTRUMENT_TYPE = {
    "EQ": InstrumentType.EQ,
    "FUT": InstrumentType.FUT,
    "CE": InstrumentType.CE,
    "PE": InstrumentType.PE,
}


def parse_master_row(row: dict[str, str]) -> Instrument | None:
    """One row of Kite's public instruments CSV -> Instrument, or None to skip.

    Columns: instrument_token, exchange_token, tradingsymbol, name,
    last_price, expiry, strike, tick_size, lot_size, instrument_type,
    segment, exchange.

    Unlike Dhan/Angel/Upstox, Kite's master is already in RUPEES — both
    `tick_size` and `strike` need no /100 (verified against real rows:
    RELIANCE tick 0.1, NIFTY option tick 0.05 / strike 23900, which is
    exactly what the other three adapters produce after their paise
    division). Kite's master also has no ISIN column, so isin stays None
    here — same as Fyers and Angel.
    """
    mapped = _MASTER_EXCH.get(row.get("exchange", ""))
    if mapped is None:
        return None
    exchange, segment = mapped

    if row.get("segment") == _INDEX_SEGMENT:
        instrument_type = InstrumentType.IDX
    else:
        found = _INSTRUMENT_TYPE.get(row.get("instrument_type", ""))
        if found is None:
            return None
        instrument_type = found

    is_derivative = instrument_type in (
        InstrumentType.FUT,
        InstrumentType.CE,
        InstrumentType.PE,
    )

    return Instrument(
        symbol=row.get("tradingsymbol", "") or "",
        exchange=exchange,
        segment=segment,
        instrument_type=instrument_type,
        name=row.get("name", "") or "",
        isin=None,
        exchange_token=row.get("exchange_token") or None,
        lot_size=_int(row.get("lot_size"), default=1),
        tick_size=_tick_size(row.get("tick_size")),
        expiry=_master_expiry(row.get("expiry", "")),
        strike=_master_strike(row.get("strike", "")),
        underlying=(row.get("name") or None) if is_derivative else None,
    )


def _master_expiry(raw: str) -> date | None:
    """Kite's master expiry is clean ISO "YYYY-MM-DD"; empty for cash/index."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _master_strike(raw: str) -> Decimal | None:
    """Already in rupees. "0" is the non-option placeholder -> None (same
    "futures strike zero -> None" quirk Groww and Dhan both have)."""
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError):
        return None
    return value if value > 0 else None


def _tick_size(raw: str | None) -> Decimal:
    if not raw:
        return Decimal("0.05")
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError):
        return Decimal("0.05")
    # Index rows carry tick_size 0 (they aren't tradeable). Keep the real
    # value rather than inventing one — the cross-broker check already
    # established that index tick sizes legitimately differ per broker.
    return value


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
# Kite's order-type strings map 1:1 onto core, including the hyphen in SL-M.
_ORDER_TYPE_TO_KITE = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL",
    OrderType.SL_M: "SL-M",
}
_ORDER_TYPE_FROM_KITE = {v: k for k, v in _ORDER_TYPE_TO_KITE.items()}

# Kite's `variety` is a separate axis from order_type (same shape as Angel's,
# different values): regular / amo / co / iceberg / auction. This adapter
# places only "regular" orders (AMO/CO/iceberg/auction are out of v1 scope,
# same YAGNI call as every prior adapter's dropped order types) — but
# modify/cancel still need the variety of the *existing* order, which core
# `Order` doesn't carry, so both read it back off the order book first.
VARIETY_REGULAR = "regular"

_PRODUCT_TO_KITE = {
    Product.CNC: "CNC",
    Product.MIS: "MIS",
    Product.NRML: "NRML",
}
# CO (cover), BO (bracket) and MTF (margin trading facility) are real Kite
# products with no distinct core value. This adapter never *places* them, but
# they can appear on orders placed elsewhere (Kite web/mobile), so reads map
# them to the nearest core product rather than raising and crashing the whole
# order list: CO and BO are intraday products -> MIS, MTF is a delivery-style
# leveraged product -> CNC.
#
# BO was nearly omitted here on the belief that Zerodha had discontinued it —
# but a live `profile` call on a real account (2026-07-21) returned
# products: ["CNC","NRML","MIS","BO","CO"], i.e. the account still advertises
# BO. Whether new BO orders can actually be placed is a separate question;
# for a *read* mapping, what matters is that the value can show up, and an
# unmapped one would raise ValueError mid-list.
_PRODUCT_FROM_KITE = {
    "CNC": Product.CNC,
    "MIS": Product.MIS,
    "NRML": Product.NRML,
    "CO": Product.MIS,
    "BO": Product.MIS,
    "MTF": Product.CNC,
}

# Kite's OMS statuses. Same semantic split as Fyers/Dhan/Angel: an order
# working AT the exchange ("OPEN", "TRIGGER PENDING") is core OPEN, while one
# still in transit / not yet accepted ("VALIDATION PENDING", "PUT ORDER REQ
# RECEIVED", "OPEN PENDING") is core PENDING. "CANCEL PENDING"/"MODIFY
# PENDING" stay OPEN — the order is still live at the exchange while the
# request is in flight. Unknown -> raise (loud beats a silently wrong
# bucket), same policy as Groww/Dhan/Angel.
_STATUS_MAP = {
    "OPEN": OrderStatus.OPEN,
    "TRIGGER PENDING": OrderStatus.OPEN,
    "MODIFY PENDING": OrderStatus.OPEN,
    "CANCEL PENDING": OrderStatus.OPEN,
    "AMO REQ RECEIVED": OrderStatus.PENDING,
    "OPEN PENDING": OrderStatus.PENDING,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
    "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
    "COMPLETE": OrderStatus.EXECUTED,
    "CANCELLED": OrderStatus.CANCELLED,
    "CANCELLED AMO": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
}


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[(raw or "").strip().upper()]
    except KeyError:
        raise ValueError(f"Unknown Kite order status: {raw!r}") from None


def map_product(raw: str) -> Product:
    try:
        return _PRODUCT_FROM_KITE[(raw or "").strip().upper()]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Kite product: {raw!r}") from None


def map_order_type(raw: str) -> OrderType:
    try:
        return _ORDER_TYPE_FROM_KITE[(raw or "").strip().upper()]
    except KeyError:
        raise ValueError(f"Unknown Kite order type: {raw!r}") from None


def map_validity(raw: str) -> Validity:
    """Kite has a third validity, TTL (a minutes-limited order). Core has no
    TTL value, so it degrades to DAY rather than raising — a TTL order is
    still a day-scoped order, and this only ever affects reads of orders
    placed outside brokerkit."""
    value = (raw or "").strip().upper()
    if value == "IOC":
        return Validity.IOC
    return Validity.DAY


def order_type_to_kite(order_type: OrderType) -> str:
    return _ORDER_TYPE_TO_KITE[order_type]


def product_to_kite(product: Product) -> str:
    return _PRODUCT_TO_KITE[product]


def order_request_to_kite(request: OrderRequest) -> dict[str, Any]:
    """OrderRequest -> KiteConnect.place_order kwargs. The SDK drops None
    values itself, so optional price/trigger_price are passed as-is."""
    inst = request.instrument
    return {
        "variety": VARIETY_REGULAR,
        "exchange": to_kite_exchange(inst),
        "tradingsymbol": inst.symbol,
        "transaction_type": request.transaction_type.value,
        "quantity": request.quantity,
        "product": product_to_kite(request.product),
        "order_type": order_type_to_kite(request.order_type),
        "validity": request.validity.value,
        "price": float(request.price) if request.price is not None else None,
        "trigger_price": (
            float(request.trigger_price) if request.trigger_price is not None else None
        ),
    }


def kite_to_order(data: dict[str, Any]) -> Order:
    """One order-book / order-history entry -> Order."""
    exchange, segment = from_kite_exchange(data["exchange"])
    return Order(
        order_id=str(data["order_id"]),
        status=map_status(data.get("status") or ""),
        trading_symbol=data.get("tradingsymbol") or "",
        exchange=exchange,
        segment=segment,
        transaction_type=TransactionType(data["transaction_type"]),
        order_type=map_order_type(data["order_type"]),
        product=map_product(data["product"]),
        validity=map_validity(data.get("validity") or "DAY"),
        quantity=_int(data.get("quantity")),
        filled_quantity=_int(data.get("filled_quantity")),
        price=_decimal(data.get("price")),
        trigger_price=_decimal(data.get("trigger_price")),
        average_price=_decimal(data.get("average_price")),
        status_message=data.get("status_message") or None,
        created_at=_as_ist(data.get("order_timestamp")),
        updated_at=_as_ist(data.get("exchange_update_timestamp"))
        or _as_ist(data.get("order_timestamp")),
    )


def place_response_to_order(order_id: str, request: OrderRequest) -> Order:
    """Kite's place_order returns only an order_id (the SDK unwraps the
    envelope down to `data["order_id"]`), so the initial state is PENDING
    and everything else is echoed from the request — same shape as the
    Fyers/Angel place responses. Re-fetch via get_order() for the
    authoritative post-fill state."""
    inst = request.instrument
    return Order(
        order_id=str(order_id),
        status=OrderStatus.PENDING,
        trading_symbol=inst.symbol,
        exchange=inst.exchange,
        segment=inst.segment,
        transaction_type=request.transaction_type,
        order_type=request.order_type,
        product=request.product,
        validity=request.validity,
        quantity=request.quantity,
        price=request.price,
        trigger_price=request.trigger_price,
    )


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------
def kite_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data.get("tradingsymbol") or "",
        isin=data.get("isin") or None,
        quantity=_int(data.get("quantity")),
        average_price=_decimal(data.get("average_price")) or Decimal("0"),
        pledged_quantity=_int(data.get("collateral_quantity")),
        t1_quantity=_int(data.get("t1_quantity")),
    )


def kite_to_position(data: dict[str, Any]) -> Position:
    exchange, segment = from_kite_exchange(data["exchange"])
    return Position(
        trading_symbol=data.get("tradingsymbol") or "",
        exchange=exchange,
        segment=segment,
        product=map_product(data["product"]),
        quantity=_int(data.get("quantity")),
        buy_quantity=_int(data.get("buy_quantity")),
        buy_price=_decimal(data.get("buy_price")),
        sell_quantity=_int(data.get("sell_quantity")),
        sell_price=_decimal(data.get("sell_price")),
        realised_pnl=_decimal(data.get("realised")),
        isin=None,  # Kite's positions response carries no ISIN
    )


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------
def kite_to_ohlc(data: dict[str, Any] | None) -> Ohlc:
    data = data or {}
    return Ohlc(
        open=_decimal(data.get("open")) or Decimal("0"),
        high=_decimal(data.get("high")) or Decimal("0"),
        low=_decimal(data.get("low")) or Decimal("0"),
        close=_decimal(data.get("close")) or Decimal("0"),
    )


def _depth(levels: Any) -> list[DepthLevel]:
    """Kite depth entries are {price, quantity, orders}. Unlike Angel, Kite
    does not appear to zero-pad missing levels — but padding rows are
    dropped here anyway rather than surfacing a Rs 0 price, which is the
    concrete bug that cost the Angel adapter a bad ask_price."""
    out: list[DepthLevel] = []
    if not isinstance(levels, list):
        return out
    for level in levels:
        if not isinstance(level, dict):
            continue
        price = _decimal(level.get("price"))
        quantity = _int(level.get("quantity"))
        if price is None or (price == 0 and quantity == 0):
            continue
        out.append(DepthLevel(price=price, quantity=quantity))
    return out


def kite_to_quote(data: dict[str, Any], instrument: Instrument) -> Quote:
    """A single entry of the /quote response -> Quote. Kite's full quote is
    the richest of any adapter here: OHLC, volume, 5-level depth, OI,
    circuit limits, average price and the last trade time all in one call."""
    depth = data.get("depth") or {}
    buy_depth = _depth(depth.get("buy"))
    sell_depth = _depth(depth.get("sell"))
    ohlc = kite_to_ohlc(data.get("ohlc"))
    last_price = _decimal(data.get("last_price")) or Decimal("0")

    day_change = None
    day_change_perc = None
    if ohlc.close:
        day_change = last_price - ohlc.close
        day_change_perc = float(day_change / ohlc.close * 100)

    return Quote(
        last_price=last_price,
        ohlc=ohlc,
        volume=_int(data.get("volume") or data.get("volume_traded")),
        day_change=day_change,
        day_change_perc=day_change_perc,
        bid_price=buy_depth[0].price if buy_depth else None,
        bid_quantity=buy_depth[0].quantity if buy_depth else None,
        ask_price=sell_depth[0].price if sell_depth else None,
        ask_quantity=sell_depth[0].quantity if sell_depth else None,
        buy_depth=buy_depth,
        sell_depth=sell_depth,
        upper_circuit=_decimal(data.get("upper_circuit_limit")),
        lower_circuit=_decimal(data.get("lower_circuit_limit")),
        open_interest=_oi(data.get("oi"), instrument),
        average_price=_decimal(data.get("average_price")),
        last_trade_time=_as_ist(data.get("last_trade_time")),
    )


def _oi(value: Any, instrument: Instrument) -> float | None:
    """Open interest only means anything for derivatives. Kite returns oi 0
    for cash instruments; null it rather than reporting a real-looking 0
    (the Angel adapter had to do the same after RELIANCE-EQ came back with a
    junk OI value)."""
    if instrument.segment not in (Segment.FNO, Segment.COMMODITY):
        return None
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def kite_to_candle(row: dict[str, Any]) -> Candle:
    """kiteconnect's historical_data() already parses the raw candle arrays
    into dicts with real datetimes (see _format_historical in the SDK), so
    this only converts types."""
    return Candle(
        timestamp=_as_ist(row.get("date")) or datetime.now(IST),
        open=_decimal(row.get("open")) or Decimal("0"),
        high=_decimal(row.get("high")) or Decimal("0"),
        low=_decimal(row.get("low")) or Decimal("0"),
        close=_decimal(row.get("close")) or Decimal("0"),
        volume=_int(row.get("volume")),
    )


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------
def feed_to_tick(instrument: Instrument, data: dict[str, Any]) -> Tick:
    """KiteTicker parses the binary feed itself (unlike Groww/Dhan/Angel,
    where the adapter unpacks bytes) and hands over dicts with prices ALREADY
    divided into rupees — the per-segment divisor (100, or 10^7 for CDS /
    10^4 for BCD) is applied inside the SDK's _parse_binary. So no scaling
    happens here.

    "full" mode is used (not "quote") for two reasons: quote-mode packets
    carry no timestamp at all — only the 184-byte full packet has
    exchange_timestamp — and full mode is also the only one with open
    interest. Volume is present in both.

    Index packets are a different shape entirely (28/32 bytes): no volume, no
    OI, no depth. Their absent keys correctly fall back to 0/None here.
    """
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        ltp=_decimal(data.get("last_price")) or Decimal("0"),
        timestamp=_as_ist(data.get("exchange_timestamp")),
        volume=_int(data.get("volume_traded")),
        open_interest=_oi(data.get("oi"), instrument),
        # Kite's feed has no server-computed minute candle (only day OHLC) —
        # same bucket as Fyers/Dhan/Angel; only Upstox provides one.
        minute_ohlc=None,
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return default


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _as_ist(value: Any) -> datetime | None:
    """Both kiteconnect's REST helpers and KiteTicker build datetimes with a
    bare `datetime.fromtimestamp(...)` / dateutil parse and NO timezone — so
    they arrive naive, in the machine's local time. Kite's own timestamps are
    always IST, so a naive value is stamped as IST rather than assumed to be
    whatever the host is set to. (This silently produces correct results on
    an IST machine and wrong ones anywhere else, which is exactly the kind of
    thing worth pinning down rather than inheriting.)"""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=IST) if value.tzinfo is None else value.astimezone(IST)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)
    return None
