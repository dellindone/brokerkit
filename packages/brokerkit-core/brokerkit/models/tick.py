from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import Exchange, Segment
from brokerkit.models.quote import Ohlc


class Tick(BaseModel):
    symbol: str
    exchange: Exchange
    segment: Segment
    ltp: Decimal
    timestamp: datetime | None = None
    volume: int = 0
    open_interest: float | None = None
    # Server-computed, continuously-updating current-minute candle — only
    # populated where the broker's feed actually pushes one (Upstox's
    # "full" streaming mode does, keyed there by an "I1" OHLC entry
    # alongside the tick); None for brokers/adapters that don't.
    minute_ohlc: Ohlc | None = None
