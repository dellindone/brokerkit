"""The market-information provider interface (optional capability)."""

from abc import ABC, abstractmethod
from datetime import date

from brokerkit.models.instrument import Instrument
from brokerkit.models.market_information import (
    ChangeInOpenInterest,
    InstitutionalActivity,
    MarketHoliday,
    MarketStatus,
    ExchangeTiming,
    MaxPain,
    MtfSmartlist,
    OpenInterest,
    Pcr,
    Smartlist,
)


class MarketInformationProvider(ABC):
    """Upstox's "Market Information" category — institutional-grade F&O
    analytics (OI/change-in-OI/max-pain/PCR per strike, FII/DII flows),
    ranked screeners (futures/options/MTF smartlists), and market
    calendar/status. No Groww/Fyers equivalent exists for any of this, so —
    same call as FundamentalsProvider/NewsProvider — this is not on the
    shared `Broker` base class, only on adapters that actually implement it.

    `expiry` on the OI/PCR/max-pain family accepts either an ISO date
    string or one of Upstox's own keywords (`current_week`/`next_week`/
    `far_week`/`current_month`/`next_month`/`far_month`) — kept as a plain
    str rather than a `date` for that reason.
    """

    @abstractmethod
    async def get_oi(self, underlying: Instrument, expiry: str, for_date: date) -> OpenInterest:
        """Return the open-interest distribution across strikes for an expiry."""

    @abstractmethod
    async def get_change_in_oi(
        self, underlying: Instrument, expiry: str, for_date: date, lookback_days: int
    ) -> ChangeInOpenInterest:
        """Return the change in open interest across strikes over a lookback window."""

    @abstractmethod
    async def get_max_pain(
        self, underlying: Instrument, expiry: str, for_date: date, bucket_interval_minutes: int
    ) -> MaxPain:
        """Return the max-pain level for an expiry."""

    @abstractmethod
    async def get_pcr(
        self, underlying: Instrument, expiry: str, for_date: date, bucket_interval_minutes: int
    ) -> Pcr:
        """Return the put-call ratio for an expiry."""

    @abstractmethod
    async def get_fii_activity(
        self, segment: str, interval: str, from_date: date | None = None
    ) -> dict[str, list[InstitutionalActivity]]:
        """`segment`: one of NSE_FO|INDEX_FUTURES, NSE_FO|STOCK_FUTURES,
        NSE_FO|INDEX_OPTIONS, NSE_FO|STOCK_OPTIONS, NSE_EQ|CASH.
        `interval`: "1D" or "1M". Result keyed by `segment` (matches
        Upstox's own response shape, even though only one key is ever
        populated per call)."""

    @abstractmethod
    async def get_dii_activity(
        self, interval: str, from_date: date | None = None
    ) -> list[InstitutionalActivity]:
        """NSE Cash market only — Upstox's `data_type` param has exactly
        one allowed value here, so unlike get_fii_activity there's nothing
        to parametrize or key the result by."""

    @abstractmethod
    async def get_futures_smartlist(
        self, asset_type: str, category: str, page_number: int = 1, page_size: int = 50
    ) -> Smartlist:
        """Return a ranked screener of futures instruments."""

    @abstractmethod
    async def get_options_smartlist(
        self, asset_type: str, category: str, page_number: int = 1, page_size: int = 50
    ) -> Smartlist:
        """Return a ranked screener of options instruments."""

    @abstractmethod
    async def get_mtf_smartlist(self, page_number: int = 1, page_size: int = 50) -> MtfSmartlist:
        """Return a ranked screener of margin-trading-facility instruments."""

    @abstractmethod
    async def get_market_holidays(self) -> list[MarketHoliday]:
        """Return the market holidays for the year."""

    @abstractmethod
    async def get_exchange_timings(self, for_date: date) -> list[ExchangeTiming]:
        """Return session open and close times per exchange for a date."""

    @abstractmethod
    async def get_market_status(self, exchange: str) -> MarketStatus:
        """Return whether an exchange is currently open."""
