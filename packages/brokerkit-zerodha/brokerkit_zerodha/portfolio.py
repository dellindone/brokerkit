"""Zerodha portfolio provider."""

import asyncio

from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors


class ZerodhaPortfolio(PortfolioProvider):
    """Zerodha portfolio provider. See
    :class:`~brokerkit.interfaces.portfolio.PortfolioProvider`."""
    def __init__(self, client):
        self._client = client  # shared KiteConnect

    async def holdings(self) -> list[Holding]:
        with zerodha_errors():
            raw = await asyncio.to_thread(self._client.holdings)
        return [mapper.kite_to_holding(h) for h in raw or []]

    async def positions(self) -> list[Position]:
        """Kite's positions response is a dict with two lists, not a flat
        list: `net` (carry-forward + intraday netted, the real current
        position) and `day` (today's trades only). `net` is the one that
        matches every other adapter's notion of a position."""
        with zerodha_errors():
            raw = await asyncio.to_thread(self._client.positions)
        net = (raw or {}).get("net") or []
        return [mapper.kite_to_position(p) for p in net]
