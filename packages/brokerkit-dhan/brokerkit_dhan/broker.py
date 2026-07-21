"""Dhan broker assembly."""

import asyncio
from datetime import datetime

from dhanhq import DhanContext, dhanhq

from brokerkit.assembly import Broker
from brokerkit.utils.datetime import IST

from brokerkit_dhan.auth import DhanAuth
from brokerkit_dhan.global_stocks import DhanGlobalStocks
from brokerkit_dhan.historical import DhanHistoricalData
from brokerkit_dhan.instruments import DhanInstruments
from brokerkit_dhan.market import DhanMarketData
from brokerkit_dhan.order import DhanOrderProvider
from brokerkit_dhan.portfolio import DhanPortfolio
from brokerkit_dhan.risk_control import DhanRiskControl
from brokerkit_dhan.streaming import DhanStreaming

_SANDBOX_BASE_URL = "https://sandbox.dhan.co/v2"


class DhanBroker(Broker):
    """Dhan broker: authenticates and wires up every provider. See
    :class:`~brokerkit.assembly.broker.Broker`."""
    name = "dhan"

    def __init__(
        self,
        client_id: str,
        pin: str | None,
        totp_secret: str | None,
        access_token: str | None,
        sandbox_access_token: str | None,
    ):
        self.auth = DhanAuth(
            client_id=client_id, pin=pin, totp_secret=totp_secret, access_token=access_token
        )
        self._client_id = client_id
        self._sandbox_access_token = sandbox_access_token
        self._context: DhanContext | None = None
        self._dhan = None
        self.instruments = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None
        self.streaming = None
        # Dhan-exclusive extras (off the shared Broker base)
        self.global_stocks = None
        self.risk_control = None
        self.sandbox_orders = None
        self._refresh_task = None

    @classmethod
    async def create(
        cls,
        client_id: str,
        pin: str | None = None,
        totp_secret: str | None = None,
        access_token: str | None = None,
        sandbox_access_token: str | None = None,
    ) -> "DhanBroker":
        broker = cls(client_id, pin, totp_secret, access_token, sandbox_access_token)
        token = await broker.auth.get_token()

        broker._context = DhanContext(client_id, token.token)
        broker._dhan = dhanhq(broker._context)

        broker.instruments = DhanInstruments()
        broker.orders = DhanOrderProvider(broker._dhan)
        broker.portfolio = DhanPortfolio(broker._dhan)
        broker.market = DhanMarketData(broker._dhan)
        broker.historical = DhanHistoricalData(broker._dhan)
        broker.streaming = DhanStreaming(broker._context)
        broker.global_stocks = DhanGlobalStocks(broker._dhan)
        broker.risk_control = DhanRiskControl(broker._dhan)

        # Sandbox: a completely separate DhanContext on a sandbox token,
        # base_url repointed at sandbox.dhan.co. Kept as its own attribute
        # (never merged into `orders`) so `broker.orders.place_order()` can
        # never silently mean sandbox — same safety design as Upstox's
        # `broker.sandbox_orders`. Dhan's sandbox covers order reads too, so
        # the *same* DhanOrderProvider class works unchanged (unlike Upstox,
        # whose sandbox had to disable get/modify/cancel).
        if sandbox_access_token:
            sandbox_context = DhanContext(client_id, sandbox_access_token)
            sandbox_context.get_dhan_http().base_url = _SANDBOX_BASE_URL
            broker.sandbox_orders = DhanOrderProvider(dhanhq(sandbox_context))

        broker._refresh_task = asyncio.create_task(broker._auto_refresh_loop())
        return broker

    async def _auto_refresh_loop(self) -> None:
        """Sleep until the token's assumed 24h expiry, then re-login and
        push the fresh token onto the shared DhanHTTP. DhanHTTP caches the
        token like FyersModel (both `.access_token` and the built
        `header['access-token']`, never re-read live — verified in
        dhan_http.py), so BOTH must be mutated or the refresh silently never
        takes effect. Known limitation: an already-running MarketFeed
        captured the old token at construction and won't pick this up (same
        streaming-refresh gap as Groww/Fyers)."""
        retry_delay = 60
        while True:
            try:
                token = await self.auth.get_token()
                sleep_for = (token.expires_at - datetime.now(IST)).total_seconds()
                await asyncio.sleep(max(sleep_for, 0))
                fresh = await self.auth.login()
                http = self._context.get_dhan_http()
                http.access_token = fresh.token
                http.header["access-token"] = fresh.token
                self._context.access_token = fresh.token
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(retry_delay)

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await super().close()
