import asyncio
from datetime import datetime

from growwapi import GrowwAPI

from brokerkit.assembly import Broker
from brokerkit.utils.datetime import IST

from brokerkit_groww.auth import GrowwAuth
from brokerkit_groww.instruments import GrowwInstruments
from brokerkit_groww.order import GrowwOrderProvider
from brokerkit_groww.portfolio import GrowwPortfolio
from brokerkit_groww.market import GrowwMarketData
from brokerkit_groww.historical import GrowwHistorical
from brokerkit_groww.streaming import GrowwStreaming

class GrowwBroker(Broker):
    name = "groww"

    def __init__(self, totp_key: str, totp_secret: str):
        self.auth = GrowwAuth(totp_key=totp_key, totp_secret=totp_secret)
        self.instruments = None
        self._client = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None
        self.streaming = None
        self._refresh_task = None

    @classmethod
    async def create(cls, totp_key: str, totp_secret: str):
        broker = cls(totp_key=totp_key, totp_secret=totp_secret)
        token = await broker.auth.get_token()
        broker._client = GrowwAPI(token.token)
        broker.instruments = GrowwInstruments(client=broker._client)
        broker.orders = GrowwOrderProvider(client=broker._client)
        broker.portfolio = GrowwPortfolio(client=broker._client)
        broker.market = GrowwMarketData(client=broker._client)
        broker.historical = GrowwHistorical(client=broker._client)
        broker.streaming = GrowwStreaming(client=broker._client)
        broker._refresh_task = asyncio.create_task(broker._auto_refresh_loop())
        return broker

    async def _auto_refresh_loop(self) -> None:
        """Groww token dies at a fixed 6 AM IST daily — sleep till expiry
        instead of checking before every call. growwapi reads
        `client.token` fresh per request, so mutating it here updates
        every already-constructed provider (they all share this client).
        """
        retry_delay = 60
        while True:
            try:
                token = await self.auth.get_token()
                sleep_for = (token.expires_at - datetime.now(IST)).total_seconds()
                await asyncio.sleep(max(sleep_for, 0))
                fresh = await self.auth.login()
                self._client.token = fresh.token
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(retry_delay)

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await super().close()
    