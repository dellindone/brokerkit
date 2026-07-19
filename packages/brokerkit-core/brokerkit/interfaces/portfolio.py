from abc import ABC, abstractmethod

from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position


class PortfolioProvider(ABC):
    @abstractmethod
    async def holdings(self) -> list[Holding]: ...

    @abstractmethod
    async def positions(self) -> list[Position]: ...
    