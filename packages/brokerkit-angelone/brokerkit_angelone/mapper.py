"""Angel One response-to-model mapping."""

from datetime import datetime
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
from brokerkit.models.instrument import Instrument
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position
from brokerkit.models.tick import Tick
from brokerkit.utils.datetime import IST

# --------------------------------------------------------------------------
# Exchange / segment
# --------------------------------------------------------------------------
# Angel's `exch_seg` (master) / `exchange` (order/quote params) strings.
# CDS (currency) / NCDEX / NCO (NSE commodity) have no clean core
# (Exchange, Segment) pair — core Exchange is NSE/BSE/MCX only and Segment
# has no CURRENCY — so those rows/instruments are dropped entirely (same
# precedent as Fyers excluding NSE_CD and Dhan excluding currency).
_TO_ANGEL_EXCH = {
    (Exchange.NSE, Segment.CASH): "NSE",
    (Exchange.NSE, Segment.FNO): "NFO",
    (Exchange.BSE, Segment.CASH): "BSE",
    (Exchange.BSE, Segment.FNO): "BFO",
    (Exchange.MCX, Segment.COMMODITY): "MCX",
}
_FROM_ANGEL_EXCH = {v: k for k, v in _TO_ANGEL_EXCH.items()}


def to_angel_exchange(instrument: Instrument) -> str:
    """Instrument -> the `exchange` string every Angel REST call needs
    (market quote / historical / order params). Indices live under their
    own exch_seg (NSE/BSE) in the master, so their (exchange, CASH) pair
    resolves here too."""
    try:
        return _TO_ANGEL_EXCH[(instrument.exchange, instrument.segment)]
    except KeyError:
        raise ValueError(
            f"No Angel exchange for {instrument.exchange}/{instrument.segment}"
        ) from None


def from_angel_exchange(value: str) -> tuple[Exchange, Segment]:
    try:
        return _FROM_ANGEL_EXCH[value]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Angel exchange: {value!r}") from None


# SmartWebSocketV2's numeric exchangeType (its own class constants:
# NSE_CM=1, NSE_FO=2, BSE_CM=3, BSE_FO=4, MCX_FO=5). Used only on the feed.
_EXCHANGE_TYPE = {
    (Exchange.NSE, Segment.CASH): 1,
    (Exchange.NSE, Segment.FNO): 2,
    (Exchange.BSE, Segment.CASH): 3,
    (Exchange.BSE, Segment.FNO): 4,
    (Exchange.MCX, Segment.COMMODITY): 5,
}


def exchange_type(instrument: Instrument) -> int:
    try:
        return _EXCHANGE_TYPE[(instrument.exchange, instrument.segment)]
    except KeyError:
        raise ValueError(
            f"No Angel feed exchangeType for {instrument.exchange}/{instrument.segment}"
        ) from None


# --------------------------------------------------------------------------
# Instrument master
# --------------------------------------------------------------------------
# exch_seg -> (Exchange, Segment). CDS/NCDEX/NCO deliberately absent.
_MASTER_EXCH = {
    "NSE": (Exchange.NSE, Segment.CASH),
    "BSE": (Exchange.BSE, Segment.CASH),
    "NFO": (Exchange.NSE, Segment.FNO),
    "BFO": (Exchange.BSE, Segment.FNO),
    "MCX": (Exchange.MCX, Segment.COMMODITY),
}

# Angel's CSV prices are in PAISE (verified live 2026-07-21 against the real
# master): NIFTY 30000-PE `strike` = "3000000.000000" = ₹30000, NIFTY option
# `tick_size` = "5.000000" = ₹0.05, SILVERMIC future `tick_size` = "100" =
# ₹1.00. Both `strike` and `tick_size` divide by 100. (The REST quote/candle
# endpoints, by contrast, return real rupee floats — only the master CSV and
# the binary websocket feed are in paise.)
_PAISE = Decimal("100")


def _index_type(instrumenttype: str) -> InstrumentType | None:
    return InstrumentType.IDX if instrumenttype in ("AMXIDX", "INDEX") else None


def parse_master_row(row: dict[str, Any]) -> Instrument | None:
    """One OpenAPIScripMaster.json row -> Instrument, or None to skip.

    Angel's master has NO ISIN column (fields are token/symbol/name/expiry/
    strike/lotsize/instrumenttype/exch_seg/tick_size/freeze_qty) — so
    Instrument.isin is always None here, same as Fyers. ISIN is only
    available per-holding on the portfolio response.
    """
    mapped = _MASTER_EXCH.get(row.get("exch_seg", ""))
    if mapped is None:
        return None  # CDS/NCDEX/NCO — no clean core mapping
    exchange, segment = mapped

    instrumenttype = row.get("instrumenttype", "") or ""
    symbol = row.get("symbol", "") or ""

    idx = _index_type(instrumenttype)
    if idx is not None:
        instrument_type: InstrumentType = idx
    elif instrumenttype == "":
        instrument_type = InstrumentType.EQ  # equity/ETF (blank type in NSE/BSE cash)
    elif instrumenttype.startswith("OPT"):
        # OPTIDX/OPTSTK/OPTFUT — CE vs PE from the trading-symbol suffix.
        if symbol.endswith("CE"):
            instrument_type = InstrumentType.CE
        elif symbol.endswith("PE"):
            instrument_type = InstrumentType.PE
        else:
            return None
    elif instrumenttype.startswith("FUT"):
        instrument_type = InstrumentType.FUT  # FUTIDX/FUTSTK/FUTCOM
    else:
        # COMDTY (commodity spot/index), UND* (underlyings) etc. — not a
        # tradeable EQ/FUT/CE/PE/IDX, drop it.
        return None

    is_derivative = instrument_type in (InstrumentType.FUT, InstrumentType.CE, InstrumentType.PE)

    return Instrument(
        symbol=symbol,
        exchange=exchange,
        segment=segment,
        instrument_type=instrument_type,
        name=row.get("name", "") or "",
        isin=None,
        exchange_token=row.get("token", "") or None,
        lot_size=_int(row.get("lotsize"), default=1),
        tick_size=_paise_or_default(row.get("tick_size")),
        expiry=_master_expiry(row.get("expiry", "")),
        strike=_master_strike(row.get("strike", "")),
        underlying=(row.get("name") or None) if is_derivative else None,
    )


def _master_expiry(raw: str) -> Any:
    """Angel master expiry is "28JUL2026" (DDMMMYYYY, uppercase month).
    strptime's %b is case-insensitive. Empty -> None."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d%b%Y").date()
    except ValueError:
        return None


def _master_strike(raw: str) -> Decimal | None:
    """Strike is in paise; "-1.000000"/"0.000000" are the non-option
    placeholders -> None."""
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (ArithmeticError, ValueError):
        return None
    return (value / _PAISE) if value > 0 else None


def _paise_or_default(raw: str | None) -> Decimal:
    if not raw:
        return Decimal("0.05")
    try:
        return Decimal(raw) / _PAISE
    except (ArithmeticError, ValueError):
        return Decimal("0.05")


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
# core OrderType.SL is a stop-*limit* (price + trigger) -> Angel
# STOPLOSS_LIMIT; SL_M is stop-market (trigger only) -> STOPLOSS_MARKET.
_ORDER_TYPE_TO_ANGEL = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "STOPLOSS_LIMIT",
    OrderType.SL_M: "STOPLOSS_MARKET",
}
_ORDER_TYPE_FROM_ANGEL = {v: k for k, v in _ORDER_TYPE_TO_ANGEL.items()}

# Angel's "variety" axis is separate from ordertype: stop-loss orders must be
# variety STOPLOSS, everything else NORMAL. (AMO/ROBO varieties are out of v1
# scope — regular orders only, same as Dhan.)
_STOPLOSS_TYPES = (OrderType.SL, OrderType.SL_M)

_PRODUCT_TO_ANGEL = {
    Product.CNC: "DELIVERY",
    Product.MIS: "INTRADAY",
    Product.NRML: "CARRYFORWARD",
}
# MARGIN (margin-trading product) has no distinct core value — mapped to the
# closest (NRML); BO/ROBO aren't placed by this adapter. Unknown -> raise.
_PRODUCT_FROM_ANGEL = {
    "DELIVERY": Product.CNC,
    "INTRADAY": Product.MIS,
    "CARRYFORWARD": Product.NRML,
    "MARGIN": Product.NRML,
}

# Angel order statuses are lowercase strings (order-book `status` field).
# Semantic split, same class of trap as Fyers/Dhan: an order that has
# reached and is working AT the exchange ("open", "trigger pending",
# "modified") is core OPEN; one still in transit / not yet accepted ("open
# pending", "validation pending", "put order req received", AMO-received) is
# core PENDING. "cancel pending"/"modify pending" -> OPEN (the order is still
# live at the exchange while the request is in flight). Unknown -> raise
# (loud > a silent wrong bucket), same policy as Groww/Dhan.
_STATUS_MAP = {
    "open": OrderStatus.OPEN,
    "trigger pending": OrderStatus.OPEN,
    "modified": OrderStatus.OPEN,
    "cancel pending": OrderStatus.OPEN,
    "modify pending": OrderStatus.OPEN,
    "not modified": OrderStatus.OPEN,
    "open pending": OrderStatus.PENDING,
    "validation pending": OrderStatus.PENDING,
    "modify validation pending": OrderStatus.PENDING,
    "put order req received": OrderStatus.PENDING,
    "after market order req received": OrderStatus.PENDING,
    "modify after market order req received": OrderStatus.PENDING,
    "complete": OrderStatus.EXECUTED,
    "cancelled": OrderStatus.CANCELLED,
    "cancelled after market order": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
}


def order_type_to_angel(order_type: OrderType) -> str:
    return _ORDER_TYPE_TO_ANGEL[order_type]


def variety_for(order_type: OrderType) -> str:
    return "STOPLOSS" if order_type in _STOPLOSS_TYPES else "NORMAL"


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[(raw or "").strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown Angel order status: {raw!r}") from None


def map_product(raw: str) -> Product:
    try:
        return _PRODUCT_FROM_ANGEL[raw]
    except KeyError:
        raise ValueError(f"Unknown/unsupported Angel producttype: {raw!r}") from None


def map_order_type(raw: str) -> OrderType:
    try:
        return _ORDER_TYPE_FROM_ANGEL[raw]
    except KeyError:
        raise ValueError(f"Unknown Angel ordertype: {raw!r}") from None


def order_request_to_angel(request: OrderRequest) -> dict[str, str]:
    """OrderRequest -> Angel placeOrder params. Angel wants string values for
    numeric fields (its own samples do); the SDK strips None keys."""
    inst = request.instrument
    return {
        "variety": variety_for(request.order_type),
        "tradingsymbol": inst.symbol,
        "symboltoken": inst.exchange_token or "",
        "transactiontype": request.transaction_type.value,
        "exchange": to_angel_exchange(inst),
        "ordertype": _ORDER_TYPE_TO_ANGEL[request.order_type],
        "producttype": _PRODUCT_TO_ANGEL[request.product],
        "duration": request.validity.value,
        "quantity": str(request.quantity),
        "price": str(request.price) if request.price is not None else "0",
        "triggerprice": str(request.trigger_price) if request.trigger_price is not None else "0",
    }


def angel_to_order(data: dict[str, Any]) -> Order:
    """One order-book entry -> Order. Prices are rupee floats here (not paise
    like the master/feed). quantity fields arrive as strings."""
    exchange, segment = from_angel_exchange(data["exchange"])
    return Order(
        order_id=str(data["orderid"]),
        status=map_status(data.get("status") or data.get("orderstatus") or ""),
        trading_symbol=data.get("tradingsymbol") or "",
        exchange=exchange,
        segment=segment,
        transaction_type=TransactionType(data["transactiontype"]),
        order_type=map_order_type(data["ordertype"]),
        product=map_product(data["producttype"]),
        validity=Validity(data.get("duration") or "DAY"),
        quantity=_int(data.get("quantity")),
        filled_quantity=_int(data.get("filledshares")),
        price=_decimal(data.get("price")),
        trigger_price=_decimal(data.get("triggerprice")),
        average_price=_decimal(data.get("averageprice")),
        status_message=data.get("text") or None,
        created_at=_order_dt(data.get("updatetime")),
        updated_at=_order_dt(data.get("updatetime")),
    )


def place_response_to_order(data: dict[str, Any], request: OrderRequest) -> Order:
    """placeOrderFullResponse's `data` is only {script, orderid,
    uniqueorderid} — no order status, so the initial state is PENDING
    (accepted, not yet confirmed at the exchange) and the rest is echoed from
    the request. Re-fetch via get_order() for the authoritative post-fill
    state, same as Fyers' id-only place response."""
    inst = request.instrument
    return Order(
        order_id=str(data["orderid"]),
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
def angel_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data.get("tradingsymbol") or "",
        isin=data.get("isin") or None,
        quantity=_int(data.get("quantity")),
        average_price=_decimal(data.get("averageprice")) or Decimal("0"),
        pledged_quantity=_int(data.get("collateralquantity")),
        t1_quantity=_int(data.get("t1quantity")),
    )


def angel_to_position(data: dict[str, Any]) -> Position:
    exchange, segment = from_angel_exchange(data["exchange"])
    return Position(
        trading_symbol=data.get("tradingsymbol") or "",
        exchange=exchange,
        segment=segment,
        product=map_product(data["producttype"]),
        quantity=_int(data.get("netqty")),
        buy_quantity=_int(data.get("buyqty")),
        buy_price=_decimal(data.get("buyavgprice")),
        sell_quantity=_int(data.get("sellqty")),
        sell_price=_decimal(data.get("sellavgprice")),
        realised_pnl=_decimal(data.get("realised")),
        isin=None,  # positions response carries no ISIN
    )


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------
# SmartWebSocketV2's binary feed sends prices as int paise (÷100) and the
# exchange timestamp as epoch milliseconds. QUOTE mode (2) carries
# volume_trade_for_the_day (LTP mode wouldn't) — chosen so Tick.volume
# populates for candle bucketing, same call as the Dhan adapter's Quote mode.
def feed_to_tick(instrument: Instrument, data: dict[str, Any]) -> Tick:
    return Tick(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        segment=instrument.segment,
        ltp=(_decimal(data.get("last_traded_price")) or Decimal("0")) / _PAISE,
        timestamp=_epoch_ms(data.get("exchange_timestamp")),
        volume=_int(data.get("volume_trade_for_the_day")),
        open_interest=None,  # only in SNAP_QUOTE (mode 3); QUOTE mode omits it
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).replace(" ", "")))
    except (ValueError, TypeError):
        return default


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(" ", ""))
    except (ArithmeticError, ValueError):
        return None


def _order_dt(value: Any) -> datetime | None:
    """Angel order timestamps are IST strings like "21-Jul-2026 12:00:00"."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None


def _epoch_ms(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=IST)
    except (ValueError, TypeError, OSError):
        return None
