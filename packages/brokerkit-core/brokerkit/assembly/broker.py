"""The Broker base class: an account\'s full provider stack."""

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
    """One authenticated broker account and every provider it offers.

    A concrete adapter subclasses this, sets :attr:`name`, and wires up the
    seven providers in :meth:`create`. Setting ``name`` also registers the
    subclass automatically, on import, so
    :func:`~brokerkit.assembly.factory.create_broker` can resolve it by name
    without core ever importing the adapter.

    Capabilities only some brokers have -- charges, fundamentals, news,
    market information, and broker-specific extras -- are deliberately *not*
    declared here. Adapters attach those as their own attributes, so no
    broker is forced to carry a provider it cannot implement.

    Use :meth:`create` rather than constructing directly; it performs the
    login and returns a fully wired instance, so a half-built broker never
    exists. Call :meth:`close` when done.
    """

    name: ClassVar[str | None] = None
    """The broker\'s registry key, e.g. ``"zerodha"``. Set by each subclass;
    setting it triggers registration."""

    instruments: InstrumentProvider
    orders: OrderProvider
    portfolio: PortfolioProvider
    market: MarketDataProvider
    historical: HistoricalDataProvider
    streaming: StreamingProvider

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register any subclass that sets ``name`` in the broker registry."""
        super().__init_subclass__(**kwargs)
        if cls.name:
            register_broker(cls.name, cls)

    @classmethod
    @abstractmethod
    async def create(cls, **config: Any) -> "Broker":
        """Authenticate and return a fully wired broker instance.

        Config keyword arguments are broker-specific -- each adapter documents
        its own. This is the factory used by
        :func:`~brokerkit.assembly.factory.create_broker`; prefer it over
        constructing the class directly.
        """

    async def close(self) -> None:
        """Release resources, closing the streaming connection if one is open.

        Adapters with a background refresh task override this to cancel it
        first, then call ``super().close()``.
        """
        streaming = getattr(self, "streaming", None)
        if streaming is not None:
            await streaming.close()
