import asyncio

from upstox_client import ApiClient, Configuration, PortfolioApi

from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.portfolio import PortfolioProvider
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import upstox_to_holding, upstox_to_position

_API_VERSION = "2.0"


class UpstoxPortfolio(PortfolioProvider):
    """Needs the OAuth token (account-scoped, and per Upstox's Analytics
    Token docs, Portfolio also needs static IP registration — same SEBI
    rule as Groww/Fyers orders)."""

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._client = PortfolioApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def holdings(self) -> list[Holding]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_holdings, _API_VERSION)
        return [upstox_to_holding(h.to_dict()) for h in resp.data or []]

    async def positions(self) -> list[Position]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_positions, _API_VERSION)
        return [upstox_to_position(p.to_dict()) for p in resp.data or []]
