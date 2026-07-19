from abc import ABC, abstractmethod
from decimal import Decimal

from brokerkit.models.instrument import Instrument
from brokerkit.models.quote import Ohlc, Quote


class MarketDataProvider(ABC):

    @abstractmethod
    async def get_quote(self, instrument: Instrument) -> Quote: ...

    @abstractmethod
    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        """Keys = instrument.symbol. Adapter batching handle karta hai."""

    @abstractmethod
    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        """Keys = instrument.symbol."""
        