"""The portfolio provider interface."""

from abc import ABC, abstractmethod

from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position


class PortfolioProvider(ABC):
    """Reads the account\'s holdings and open positions."""

    @abstractmethod
    async def holdings(self) -> list[Holding]:
        """Return long-term holdings settled in the demat account.

        An empty account returns an empty list. Note that at least one broker
        reports "no holdings" as an error rather than an empty response; its
        adapter translates that back into ``[]``.
        """

    @abstractmethod
    async def positions(self) -> list[Position]:
        """Return open positions for the current trading day."""
