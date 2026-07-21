from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from brokerkit.enums import (
    Exchange, InstrumentType, OrderStatus, OrderType, Product, Segment, TransactionType, Validity,
)
from brokerkit.models.instrument import Instrument
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position
from brokerkit.models.tick import Tick

# Dhan's REST exchangeSegment strings (Annexure "Exchange Segment" table).
# IDX_I (index) has no tradeable core (Exchange, Segment) — indices map to
# an Exchange the way instruments.py does (CASH), but it's only ever used
# for market-data/option-chain underlyings, never orders/positions.
_SEGMENT_TO_DHAN = {
    (Exchange.NSE, Segment.CASH): "NSE_EQ",
    (Exchange.NSE, Segment.FNO): "NSE_FNO",
    (Exchange.BSE, Segment.CASH): "BSE_EQ",
    (Exchange.BSE, Segment.FNO): "BSE_FNO",
    (Exchange.MCX, Segment.COMMODITY): "MCX_COMM",
}
_SEGMENT_FROM_DHAN = {
    "NSE_EQ": (Exchange.NSE, Segment.CASH),
    "NSE_FNO": (Exchange.NSE, Segment.FNO),
    "BSE_EQ": (Exchange.BSE, Segment.CASH),
    "BSE_FNO": (Exchange.BSE, Segment.FNO),
    "MCX_COMM": (Exchange.MCX, Segment.COMMODITY),
    # IDX_I intentionally absent — never appears on an order/position.
}


def dhan_segment(instrument: Instrument) -> str:
    """Instrument -> the exchangeSegment string every Dhan REST call needs.
    Indices use IDX_I regardless of their (exchange, segment)."""
    if instrument.instrument_type is InstrumentType.IDX:
        return "IDX_I"
    try:
        return _SEGMENT_TO_DHAN[(instrument.exchange, instrument.segment)]
    except KeyError:
        raise ValueError(
            f"No Dhan exchangeSegment for {instrument.exchange}/{instrument.segment}"
        ) from None


def segment_from_dhan(value: str) -> tuple[Exchange, Segment]:
    try:
        return _SEGMENT_FROM_DHAN[value]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Dhan exchangeSegment: {value!r}") from None


# The historical-data API needs Dhan's own `instrument` classification
# (INDEX/EQUITY/FUTIDX/FUTSTK/OPTIDX/OPTSTK/FUTCOM/OPTFUT) which core's
# InstrumentType (EQ/FUT/CE/PE/IDX) can't fully express — the FNO idx-vs-stk
# split is lost. Reconstructed from the underlying: this is the complete
# set of index underlyings in Dhan's master (live-verified 2026-07-21 —
# only 11, vs 228 stock underlyings), so membership cleanly resolves the
# split. May need extending if Dhan lists a new index; kept as data, not
# guessed. MCXBULLDEX/MCXMETLDEX are commodity-*index* products Dhan still
# classifies FUTIDX/OPTIDX (not FUTCOM) — the index check runs first so
# they resolve correctly.
_INDEX_UNDERLYINGS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "SENSEX", "BANKEX", "SENSEX50", "BANKEX", "FOCIT",
    "MCXBULLDEX", "MCXMETLDEX",
}


def dhan_instrument_type(instrument: Instrument) -> str:
    """Instrument -> Dhan's `instrument` string for historical-data calls."""
    if instrument.instrument_type is InstrumentType.IDX:
        return "INDEX"
    if instrument.instrument_type is InstrumentType.EQ:
        return "EQUITY"
    is_fut = instrument.instrument_type is InstrumentType.FUT
    if (instrument.underlying or "").upper() in _INDEX_UNDERLYINGS:
        return "FUTIDX" if is_fut else "OPTIDX"
    if instrument.segment is Segment.COMMODITY:
        return "FUTCOM" if is_fut else "OPTFUT"
    return "FUTSTK" if is_fut else "OPTSTK"


# core OrderType.SL is a stop-*limit* (price + trigger), Dhan's STOP_LOSS;
# core SL_M is stop-market (trigger only), Dhan's STOP_LOSS_MARKET.
_ORDER_TYPE_TO_DHAN = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "STOP_LOSS",
    OrderType.SL_M: "STOP_LOSS_MARKET",
}
_ORDER_TYPE_FROM_DHAN = {v: k for k, v in _ORDER_TYPE_TO_DHAN.items()}

# core Product has no MTF — dropped like Fyers/Groww dropped their SDK
# extras (unverified in this framework; add only when implemented+tested).
_PRODUCT_TO_DHAN = {Product.CNC: "CNC", Product.MIS: "INTRADAY", Product.NRML: "MARGIN"}
_PRODUCT_FROM_DHAN = {"CNC": Product.CNC, "INTRADAY": Product.MIS, "MARGIN": Product.NRML}

# Dhan order statuses (Annexure "Order Status"). Semantic trap, same class
# as Fyers': Dhan "PENDING" means the order is live/working AT the exchange
# (core OPEN), while "TRANSIT" means it hasn't reached the exchange yet
# (core PENDING) — opposite of what the names suggest. PART_TRADED is still
# a live/working order (core OPEN). EXPIRED/INACTIVE have no clean canonical
# match — FAILED is the closest (order didn't survive to execution).
# MODIFIED/TRIGGERED come up on super-order legs (out of v1 scope) but are
# mapped to OPEN for completeness since a regular modify response can echo
# MODIFIED.
_STATUS_MAP = {
    "TRANSIT": OrderStatus.PENDING,
    "PENDING": OrderStatus.OPEN,
    "PART_TRADED": OrderStatus.OPEN,
    "MODIFIED": OrderStatus.OPEN,
    "TRIGGERED": OrderStatus.OPEN,
    "TRADED": OrderStatus.EXECUTED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.FAILED,
    "INACTIVE": OrderStatus.FAILED,
}


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"Unknown Dhan order status: {raw!r}") from None


def map_product(raw: str) -> Product:
    try:
        return _PRODUCT_FROM_DHAN[raw]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Dhan productType: {raw!r}") from None


def order_type_to_dhan(order_type: OrderType) -> str:
    return _ORDER_TYPE_TO_DHAN[order_type]


def _decimal(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


def _dt(v: Any) -> datetime | None:
    """Dhan order timestamps are IST strings like "2021-11-24 13:33:03"."""
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def order_request_to_dhan(request: OrderRequest) -> dict[str, Any]:
    """kwargs for dhanhq's Order.place_order(). It requires `price` (float,
    MARKET uses 0) and `trigger_price` (float); security_id is the
    exchange_token, exchange_segment the Annexure string."""
    return {
        "security_id": request.instrument.exchange_token,
        "exchange_segment": dhan_segment(request.instrument),
        "transaction_type": request.transaction_type.value,
        "quantity": request.quantity,
        "order_type": _ORDER_TYPE_TO_DHAN[request.order_type],
        "product_type": _PRODUCT_TO_DHAN[request.product],
        "price": float(request.price) if request.price is not None else 0,
        "trigger_price": float(request.trigger_price) if request.trigger_price is not None else 0,
        "validity": request.validity.value,
    }


def dhan_to_order(data: dict[str, Any]) -> Order:
    """Orderbook / get-order item -> Order. exchangeSegment is the string
    form; tradingSymbol is present on these responses."""
    exchange, segment = segment_from_dhan(data["exchangeSegment"])
    return Order(
        order_id=data["orderId"],
        status=map_status(data["orderStatus"]),
        trading_symbol=data.get("tradingSymbol") or "",
        exchange=exchange,
        segment=segment,
        transaction_type=TransactionType(data["transactionType"]),
        order_type=_ORDER_TYPE_FROM_DHAN[data["orderType"]],
        product=map_product(data["productType"]),
        validity=Validity(data["validity"]),
        quantity=data["quantity"],
        filled_quantity=data.get("filledQty") or 0,
        price=_decimal(data.get("price")) or None,
        trigger_price=_decimal(data.get("triggerPrice")) or None,
        average_price=_decimal(data.get("averageTradedPrice")) or None,
        status_message=data.get("omsErrorDescription") or None,
        created_at=_dt(data.get("createTime")),
        updated_at=_dt(data.get("updateTime")),
    )


def place_response_to_order(data: dict[str, Any], request: OrderRequest) -> Order:
    """place_order's response is just {orderId, orderStatus} — richer than
    Fyers' id-only response (we get a real status), but still no echo of the
    order details, so those come from the request. Callers needing the
    authoritative post-fill state should re-fetch via get_order()."""
    return Order(
        order_id=data["orderId"],
        status=map_status(data["orderStatus"]),
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


def dhan_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data.get("tradingSymbol") or "",
        isin=data.get("isin") or None,
        quantity=int(data.get("totalQty") or 0),
        average_price=_decimal(data.get("avgCostPrice")) or Decimal("0"),
        pledged_quantity=int(data.get("collateralQty") or 0),
        t1_quantity=int(data.get("t1Qty") or 0),
    )


def dhan_to_position(data: dict[str, Any]) -> Position:
    exchange, segment = segment_from_dhan(data["exchangeSegment"])
    return Position(
        trading_symbol=data.get("tradingSymbol") or "",
        exchange=exchange,
        segment=segment,
        product=map_product(data["productType"]),
        quantity=int(data.get("netQty") or 0),
        buy_quantity=int(data.get("buyQty") or 0),
        buy_price=_decimal(data.get("buyAvg")),
        sell_quantity=int(data.get("sellQty") or 0),
        sell_price=_decimal(data.get("sellAvg")),
        realised_pnl=_decimal(data.get("realizedProfit")),
        isin=None,  # positions response carries no ISIN
    )


# marketfeed.py's numeric exchange-segment codes (used only on the websocket
# feed, not REST). Index instruments use 0. No CURRENCY code needed (core
# has no currency segment).
_NUMERIC_SEGMENT = {
    (Exchange.NSE, Segment.CASH): 1,
    (Exchange.NSE, Segment.FNO): 2,
    (Exchange.BSE, Segment.CASH): 4,
    (Exchange.MCX, Segment.COMMODITY): 5,
    (Exchange.BSE, Segment.FNO): 8,
}


def numeric_segment(instrument: Instrument) -> int:
    if instrument.instrument_type is InstrumentType.IDX:
        return 0  # IDX_I
    try:
        return _NUMERIC_SEGMENT[(instrument.exchange, instrument.segment)]
    except KeyError:
        raise ValueError(
            f"No Dhan feed exchange code for {instrument.exchange}/{instrument.segment}"
        ) from None


def _reconstruct_ts(ltt: Any) -> datetime | None:
    """dhanhq's marketfeed pre-formats LTT via utc_time(epoch) to a bare
    "HH:MM:SS" UTC string (verified in marketfeed.py) — the epoch and date
    are discarded before on_message ever sees the packet. Reconstruct a
    usable timestamp by pinning it to today's UTC date. Good enough for
    live intraday candle bucketing (the actual use case); loses accuracy
    only across a UTC midnight boundary. A raw-binary parse override would
    be the follow-up if exact epochs are ever needed.
    """
    if not ltt or not isinstance(ltt, str):
        return None
    try:
        h, m, s = (int(x) for x in ltt.split(":"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return now.replace(hour=h, minute=m, second=s, microsecond=0)


def dhan_to_tick(instrument: Instrument, data: dict[str, Any]) -> Tick:
    """Quote-mode feed packet (marketfeed.py's process_quote dict) -> Tick.
    Quote mode carries volume + OHLC (Ticker mode wouldn't) — chosen so
    Tick.volume populates, consistent with the pipeline's candle-bucketing
    need. open_interest arrives only in the separate OI packet (feed type 5),
    not merged here in v1 — stays None (documented, not a mapping gap)."""
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        ltp=_decimal(data.get("LTP")) or Decimal("0"),
        timestamp=_reconstruct_ts(data.get("LTT")),
        volume=int(data.get("volume") or 0),
        open_interest=None,
    )
