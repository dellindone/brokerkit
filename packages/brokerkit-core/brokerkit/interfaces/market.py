from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain
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

    @abstractmethod
    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        """`underlying` = the index/stock instrument (e.g. NIFTY50-INDEX),
        not an option contract itself. `expiry` is required — no
        "nearest expiry" convenience in v1, caller must know a valid one.
        `strike_count` is advisory: brokers whose API can't filter
        strike-count-wise (e.g. Groww) may ignore it and return everything.
        """