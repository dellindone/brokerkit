"""Zerodha broker assembly."""

import asyncio
from datetime import datetime

from brokerkit.assembly import Broker
from brokerkit.utils.datetime import IST

from brokerkit_zerodha.auth import ZerodhaAuth
from brokerkit_zerodha.charges import ZerodhaCharges
from brokerkit_zerodha.gtt import ZerodhaGtt
from brokerkit_zerodha.historical import ZerodhaHistoricalData
from brokerkit_zerodha.instruments import ZerodhaInstruments
from brokerkit_zerodha.market import ZerodhaMarketData
from brokerkit_zerodha.order import ZerodhaOrderProvider
from brokerkit_zerodha.portfolio import ZerodhaPortfolio
from brokerkit_zerodha.streaming import ZerodhaStreaming


class ZerodhaBroker(Broker):
    """Kite Connect adapter.

    Plan note worth knowing before anything fails confusingly: Zerodha's free
    **Personal** plan covers orders/GTT/portfolio/margins but has **no market
    data and no historical data**; those need the paid **₹500/mo Connect**
    plan. So on a free app, `broker.market` / `broker.historical` /
    `broker.streaming` will fail on the account's subscription state, not on
    a bug here. This is the inverse of Fyers/Angel, where data is free and
    execution is what's constrained.
    """

    name = "zerodha"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ):
        self.auth = ZerodhaAuth(
            api_key=api_key,
            api_secret=api_secret,
            redirect_uri=redirect_uri,
            access_token=access_token,
        )
        self.instruments = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None
        self.streaming = None
        # Zerodha-exclusive extras (off the shared Broker base)
        self.charges = None
        self.gtt = None
        self._refresh_task = None

    @classmethod
    async def create(
        cls,
        api_key: str,
        api_secret: str,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ) -> "ZerodhaBroker":
        broker = cls(api_key, api_secret, redirect_uri, access_token)
        # Eager login (Groww/Fyers/Dhan/Angel-style, not Upstox's lazy one).
        # With access_token= this is instant and silent; without it, this is
        # where the browser opens — which is the right moment for it, since
        # an interactive first run is the only time it can be answered.
        token = await broker.auth.get_token()
        client = broker.auth.client  # the one shared KiteConnect

        broker.instruments = ZerodhaInstruments()  # public CSV, no auth
        broker.orders = ZerodhaOrderProvider(client)
        broker.portfolio = ZerodhaPortfolio(client)
        broker.market = ZerodhaMarketData(client)
        broker.historical = ZerodhaHistoricalData(client)
        broker.streaming = ZerodhaStreaming(api_key, token.token)
        broker.charges = ZerodhaCharges(client)
        broker.gtt = ZerodhaGtt(client)

        broker._refresh_task = asyncio.create_task(broker._auto_refresh_loop())
        return broker

    async def _auto_refresh_loop(self) -> None:
        """Sleep until the token's 6:00 AM IST expiry, then try to renew.

        Unlike every other adapter, this loop usually **cannot** succeed:
        Kite has no headless login, and `renew_access_token` needs a
        refresh_token that Zerodha only issues to approved platforms. When
        renewal isn't available, `auth.refresh()` raises a clear
        AuthenticationError explaining that a browser login is required —
        which is caught and retried here rather than crashing the task, but
        will keep failing until a fresh token is supplied.

        That is the honest behaviour: the alternative would be popping a
        browser window from a background task at 6 AM, where nobody could
        answer it. Same accepted-limitation posture as the Upstox adapter's
        OAuth path.

        Note KiteConnect._request rebuilds its auth header from
        `self.access_token` on every call (verified in connect.py), so when a
        refresh *does* succeed, every REST provider picks it up with no
        further wiring — the easy Groww/Upstox/Angel case. An already-open
        streaming socket keeps the old token, same limitation as every other
        adapter here.
        """
        retry_delay = 300
        while True:
            try:
                token = await self.auth.get_token()
                sleep_for = (token.expires_at - datetime.now(IST)).total_seconds()
                await asyncio.sleep(max(sleep_for, 0))
                await self.auth.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(retry_delay)

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await super().close()
