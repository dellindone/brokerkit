import asyncio

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_fyers.errors import check
from brokerkit_fyers.mapper import fyers_to_holding, fyers_to_position


class FyersPortfolio(PortfolioProvider):
    def __init__(self, client: FyersModel) -> None:
        self._client = client

    async def holdings(self) -> list[Holding]:
        resp = await asyncio.to_thread(self._client.holdings)
        check(resp)
        return [fyers_to_holding(h) for h in resp.get("holdings") or []]

    async def positions(self) -> list[Position]:
        resp = await asyncio.to_thread(self._client.positions)
        check(resp)
        return [fyers_to_position(p) for p in resp.get("netPositions") or []]
