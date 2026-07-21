import asyncio

from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_dhan.errors import check, is_no_data
from brokerkit_dhan.mapper import dhan_to_holding, dhan_to_position


class DhanPortfolio(PortfolioProvider):
    def __init__(self, dhan):
        self._dhan = dhan

    async def holdings(self) -> list[Holding]:
        resp = await asyncio.to_thread(self._dhan.get_holdings)
        if is_no_data(resp):
            return []
        data = check(resp)
        return [dhan_to_holding(h) for h in (data or [])]

    async def positions(self) -> list[Position]:
        resp = await asyncio.to_thread(self._dhan.get_positions)
        if is_no_data(resp):
            return []
        data = check(resp)
        return [dhan_to_position(p) for p in (data or [])]
