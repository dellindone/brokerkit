from abc import ABC, abstractmethod
from datetime import datetime

from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument


class HistoricalDataProvider(ABC):

    @abstractmethod
    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]: ...
    