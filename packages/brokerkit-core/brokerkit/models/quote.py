"""Market quote, OHLC and depth models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Ohlc(BaseModel):
    """Open, high, low and close for a period.

    Reused for the day-session OHLC on a quote and, on brokers whose feed
    provides one, the live minute candle on a tick.
    """

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: int | None = None
    """Quantity traded in the period. ``None`` for REST day-OHLC, which
    carries no volume of its own; populated for the streaming minute
    candle."""


class DepthLevel(BaseModel):
    """One price level of the order book."""

    price: Decimal
    quantity: int
    """Total quantity resting at this price."""


class Quote(BaseModel):
    """A market-data snapshot for one instrument.

    How much of this is filled in varies by broker, and the difference is
    real capability rather than adapter gaps: some quote endpoints return
    full depth, open interest and circuit limits in one call, while others
    return little more than the last price and day OHLC.

    Empty depth levels are dropped rather than passed through. At least one
    broker zero-pads its book to a fixed number of levels, and forwarding
    those produced a quoted ask of zero -- a price no strategy should ever
    act on.
    """

    last_price: Decimal
    """Last traded price."""

    ohlc: Ohlc
    """Day-session open, high, low and close."""

    volume: int = 0
    """Cumulative quantity traded today."""

    day_change: Decimal | None = None
    """Absolute change from the previous close."""

    day_change_perc: float | None = None
    """Percentage change from the previous close."""

    bid_price: Decimal | None = None
    bid_quantity: int | None = None
    ask_price: Decimal | None = None
    ask_quantity: int | None = None

    buy_depth: list[DepthLevel] = []
    """Bid side of the order book, best price first."""

    sell_depth: list[DepthLevel] = []
    """Ask side of the order book, best price first."""

    upper_circuit: Decimal | None = None
    lower_circuit: Decimal | None = None

    open_interest: float | None = None
    """Open interest. Meaningful only for derivatives; adapters null it for
    cash instruments, because at least one broker returns a large but
    meaningless number there."""

    average_price: Decimal | None = None
    """Volume-weighted average price for the day."""

    last_trade_time: datetime | None = None
