"""The historical-data provider interface."""

from abc import ABC, abstractmethod
from datetime import datetime

from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument


class HistoricalDataProvider(ABC):
    """Fetches historical OHLCV candles."""

    @abstractmethod
    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        """Return candles for ``instrument`` between ``start`` and ``end``.

        ``interval_minutes`` is the bar size. Brokers support a fixed set of
        intervals rather than any value, so an unsupported one raises rather
        than being silently rounded. Some also cap how much history a single
        request may span; an over-long range surfaces the broker\'s own error
        rather than being truncated.

        On brokers that charge for market data, this needs the paid data
        subscription and otherwise fails on the account\'s entitlement, not on
        anything wrong with the request.
        """
