from abc import ABC, abstractmethod
from typing import Any, ClassVar

from brokerkit.assembly.registry import register_broker

from brokerkit.interfaces import (
    HistoricalDataProvider,
    InstrumentProvider,
    MarketDataProvider,
    OrderProvider,
    PortfolioProvider,
    StreamingProvider,
)


class Broker(ABC):
    """Ek authenticated broker account ka poora provider stack.

    Subclass jo `name` set karta hai wo import hote hi registry mein
    apne aap register ho jaata hai (factory isi se `create_broker(name)`
    resolve karta hai).
    """

    name: ClassVar[str | None] = None

    instruments: InstrumentProvider
    orders: OrderProvider
    portfolio: PortfolioProvider
    market: MarketDataProvider
    historical: HistoricalDataProvider
    streaming: StreamingProvider

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            register_broker(cls.name, cls)

    @classmethod
    @abstractmethod
    async def create(cls, **config: Any) -> "Broker":
        """Authenticate karke fully-wired broker instance lautao."""

    async def close(self) -> None:
        streaming = getattr(self, "streaming", None)
        if streaming is not None:
            await streaming.close()
