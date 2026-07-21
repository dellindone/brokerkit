"""Streaming tick model."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import Exchange, Segment
from brokerkit.models.quote import Ohlc


class Tick(BaseModel):
    """A single live update from a broker's market feed.

    Delivered to the callback passed to
    :meth:`~brokerkit.interfaces.streaming.StreamingProvider.subscribe_ltp`.

    Adapters pick the feed mode that carries cumulative volume, since volume
    is what candle aggregation needs, and where a broker offers a choice they
    also prefer the mode carrying a real exchange timestamp over one that
    would force a synthesized client-side time.
    """

    symbol: str
    exchange: Exchange
    segment: Segment

    ltp: Decimal
    """Last traded price, in rupees. Several feeds transmit paise; adapters
    convert."""

    timestamp: datetime | None = None
    """Exchange timestamp for the tick, where the feed provides one."""

    volume: int = 0
    """Cumulative quantity traded today. Stays 0 for index feeds, which do
    not trade."""

    open_interest: float | None = None
    """Open interest, where the feed's mode carries it. ``None`` for cash
    instruments and for feeds that strip it."""

    minute_ohlc: Ohlc | None = None
    """Server-computed candle for the current minute.

    **Only Upstox provides this.** Every other broker's feed carries day-level
    OHLC only, so this stays ``None`` there and 1-minute candles must be
    aggregated from ticks in your own pipeline.
    """
