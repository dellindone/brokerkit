from abc import ABC, abstractmethod

from brokerkit.models.instrument import Instrument
from brokerkit.models.news import NewsArticle


class NewsProvider(ABC):
    """Market news articles, published in roughly the last week.

    Same non-universal status as FundamentalsProvider — not on the shared
    `Broker` base, adapters that implement it expose it as their own extra
    attribute. Three lookup modes, mirroring the underlying API: specific
    instruments, or the account's current positions/holdings (those two
    are resolved server-side by the broker — no instrument list needed).
    """

    @abstractmethod
    async def get_news(self, instruments: list[Instrument]) -> list[NewsArticle]: ...

    @abstractmethod
    async def get_news_for_positions(self) -> list[NewsArticle]: ...

    @abstractmethod
    async def get_news_for_holdings(self) -> list[NewsArticle]: ...
