"""Angel One broker assembly."""

import asyncio
from datetime import datetime

from brokerkit.assembly import Broker
from brokerkit.utils.datetime import IST

from brokerkit_angelone.analytics import AngelAnalytics
from brokerkit_angelone.auth import AngelAuth
from brokerkit_angelone.charges import AngelCharges
from brokerkit_angelone.historical import AngelHistoricalData
from brokerkit_angelone.instruments import AngelInstruments
from brokerkit_angelone.market import AngelMarketData
from brokerkit_angelone.order import AngelOrderProvider
from brokerkit_angelone.portfolio import AngelPortfolio
from brokerkit_angelone.streaming import AngelStreaming


class AngelBroker(Broker):
    """Angel One broker: authenticates and wires up every provider. See
    :class:`~brokerkit.assembly.broker.Broker`."""
    name = "angelone"

    def __init__(self, api_key: str, client_code: str, mpin: str, totp_secret: str):
        self.auth = AngelAuth(
            api_key=api_key,
            client_code=client_code,
            mpin=mpin,
            totp_secret=totp_secret,
        )
        self.instruments = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None
        self.streaming = None
        # Angel-exclusive extras (off the shared Broker base)
        self.charges = None
        self.analytics = None
        self._refresh_task = None

    @classmethod
    async def create(
        cls, api_key: str, client_code: str, mpin: str, totp_secret: str
    ) -> "AngelBroker":
        broker = cls(api_key, client_code, mpin, totp_secret)
        token = await broker.auth.get_token()  # eager TOTP+MPIN login
        client = broker.auth.client  # the one shared SmartConnect

        broker.instruments = AngelInstruments()  # public master, no auth
        broker.orders = AngelOrderProvider(client)
        broker.portfolio = AngelPortfolio(client)
        broker.market = AngelMarketData(client)
        broker.historical = AngelHistoricalData(client)
        broker.streaming = AngelStreaming(
            token.token, api_key, client_code, broker.auth.feed_token or ""
        )
        broker.charges = AngelCharges(client)
        broker.analytics = AngelAnalytics(client)

        broker._refresh_task = asyncio.create_task(broker._auto_refresh_loop())
        return broker

    async def _auto_refresh_loop(self) -> None:
        """Sleep until the jwt's assumed 24h expiry, then refresh via Angel's
        native `generateToken(refreshToken)` (AngelAuth.refresh) — no TOTP
        re-entry, the one adapter that has a real refresh-token endpoint.
        SmartConnect re-reads `access_token` fresh on every REST call
        (verified in smartConnect.py, like Groww/Upstox and unlike
        Fyers/Dhan's cached header), and every provider shares this one
        client, so refresh() mutating it is enough — no per-provider fix-up.

        Known limitation (same as every other adapter): an already-connected
        streaming socket captured the old jwt/feed_token and won't pick up the
        refresh; only the REST providers do."""
        retry_delay = 60
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
