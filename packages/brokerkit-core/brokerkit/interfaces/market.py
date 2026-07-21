"""The market-data provider interface."""

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain
from brokerkit.models.quote import Ohlc, Quote


class MarketDataProvider(ABC):
    """Fetches quotes, prices and option chains.

    The batch methods take a list and handle the broker\'s per-request limit
    internally, chunking as needed, and return a dict keyed by
    ``instrument.symbol``. On brokers that charge for market data, all of
    this needs the paid data subscription.
    """

    @abstractmethod
    async def get_quote(self, instrument: Instrument) -> Quote:
        """Return a full market-data snapshot for one instrument.

        How much of the :class:`~brokerkit.models.quote.Quote` is populated
        depends on what the broker\'s quote endpoint provides.
        """

    @abstractmethod
    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        """Return the last traded price for each instrument.

        Keyed by ``instrument.symbol``. Batched across the broker\'s
        per-request limit.
        """

    @abstractmethod
    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        """Return day-session OHLC for each instrument.

        Keyed by ``instrument.symbol``. Batched across the broker\'s
        per-request limit.
        """

    @abstractmethod
    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        """Return the option chain for an underlying at a given expiry.

        ``underlying`` is the index or stock instrument, not an option
        contract. ``expiry`` is required -- there is no "nearest expiry"
        convenience, so the caller must pass a valid one (see
        ``expiry_list`` on the brokers that offer it).

        ``strike_count`` is advisory: it requests roughly that many strikes
        either side of spot, but a broker whose endpoint cannot filter by
        strike count may return the whole chain.

        Some brokers serve this directly; others have no chain endpoint and
        their adapter assembles it from the instrument master plus quotes.
        Greeks are populated only where the broker provides them.
        """
