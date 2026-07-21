"""Groww portfolio provider."""

import asyncio

from growwapi import GrowwAPI

from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_groww.errors import groww_errors
from brokerkit_groww.mapper import groww_to_holding, groww_to_position

class GrowwPortfolio(PortfolioProvider):
    """Groww portfolio provider. See
    :class:`~brokerkit.interfaces.portfolio.PortfolioProvider`."""
    def __init__(self, client: GrowwAPI) -> None:
        self._client = client

    async def holdings(self) -> list[Holding]:
        with groww_errors():
            data = await asyncio.to_thread(self._client.get_holdings_for_user)
        return [groww_to_holding(h) for h in data.get("holdings", [])]

    async def positions(self) -> list[Position]:
        with groww_errors():
            data = await asyncio.to_thread(self._client.get_positions_for_user)
        return [groww_to_position(p) for p in data.get("positions", [])]
    