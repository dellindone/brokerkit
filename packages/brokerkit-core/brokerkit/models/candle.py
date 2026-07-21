"""Historical OHLCV candle."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Candle(BaseModel):
    """One OHLCV bar, as returned by
    :meth:`~brokerkit.interfaces.historical.HistoricalDataProvider.get_candles`.
    """

    timestamp: datetime
    """Start of the interval this candle covers, timezone-aware in IST."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: int = 0
    """Total quantity traded during the interval."""
