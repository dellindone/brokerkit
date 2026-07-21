"""Angel One portfolio provider."""

import asyncio

from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_angelone.errors import angel_errors, check
from brokerkit_angelone.mapper import angel_to_holding, angel_to_position


class AngelPortfolio(PortfolioProvider):
    """Angel One portfolio provider. See
    :class:`~brokerkit.interfaces.portfolio.PortfolioProvider`."""
    def __init__(self, client):
        self._client = client  # shared SmartConnect

    async def holdings(self) -> list[Holding]:
        with angel_errors():
            resp = await asyncio.to_thread(self._client.holding)
        data = check(resp)
        return [angel_to_holding(h) for h in (data or [])]

    async def positions(self) -> list[Position]:
        with angel_errors():
            resp = await asyncio.to_thread(self._client.position)
        data = check(resp)
        return [angel_to_position(p) for p in (data or [])]
