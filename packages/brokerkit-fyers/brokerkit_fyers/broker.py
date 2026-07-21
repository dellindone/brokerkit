"""Fyers broker assembly."""

import asyncio
from datetime import datetime

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.assembly import Broker
from brokerkit.utils.datetime import IST

from brokerkit_fyers.auth import FyersAuth
from brokerkit_fyers.instruments import FyersInstruments
from brokerkit_fyers.order import FyersOrderProvider
from brokerkit_fyers.portfolio import FyersPortfolio
from brokerkit_fyers.market import FyersMarketData
from brokerkit_fyers.historical import FyersHistorical
from brokerkit_fyers.streaming import FyersStreaming


class FyersBroker(Broker):
    """Fyers broker: authenticates and wires up every provider. See
    :class:`~brokerkit.assembly.broker.Broker`."""
    name = "fyers"

    def __init__(
        self,
        client_id: str,
        secret_key: str,
        redirect_uri: str,
        fy_id: str,
        totp_secret: str,
        pin: str,
    ):
        self.auth = FyersAuth(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=redirect_uri,
            fy_id=fy_id,
            totp_secret=totp_secret,
            pin=pin,
        )
        self._client_id = client_id
        self.instruments = None
        self._client = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None
        self.streaming = None
        self._refresh_task = None

    @classmethod
    async def create(
        cls,
        client_id: str,
        secret_key: str,
        redirect_uri: str,
        fy_id: str,
        totp_secret: str,
        pin: str,
    ):
        broker = cls(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=redirect_uri,
            fy_id=fy_id,
            totp_secret=totp_secret,
            pin=pin,
        )
        token = await broker.auth.get_token()
        # is_async=False deliberately, matching Groww's adapter: we wrap
        # the sync client via asyncio.to_thread everywhere rather than use
        # the SDK's own is_async=True mode, whose error-handling paths
        # (FyersServiceAsync) are visibly rougher than the sync ones when
        # reading the source — consistency with the rest of the framework
        # also matters more here than the marginal efficiency gain.
        broker._client = FyersModel(client_id=client_id, token=token.token, is_async=False)
        broker.instruments = FyersInstruments()
        broker.orders = FyersOrderProvider(client=broker._client)
        broker.portfolio = FyersPortfolio(client=broker._client)
        broker.market = FyersMarketData(client=broker._client)
        broker.historical = FyersHistorical(client=broker._client)
        broker.streaming = FyersStreaming(client_id=client_id, token=token.token)
        broker._refresh_task = asyncio.create_task(broker._auto_refresh_loop())
        return broker

    async def _auto_refresh_loop(self) -> None:
        """Sleeps until the token's assumed expiry, then does a full fresh
        TOTP+PIN login — same sleep-until-expiry shape as
        GrowwBroker._auto_refresh_loop, except Fyers gives no deterministic
        reset time like Groww's 6 AM IST (see auth.ASSUMED_VALIDITY), so
        the "expiry" here is a conservative assumption, not a known fact.
        """
        retry_delay = 60
        while True:
            try:
                token = await self.auth.get_token()
                sleep_for = (token.expires_at - datetime.now(IST)).total_seconds()
                await asyncio.sleep(max(sleep_for, 0))
                fresh = await self.auth.login()
                # FyersModel caches "client_id:token" as `.header` at
                # construction time (verified from SDK source — every API
                # call uses self.header, not a live re-read of .token), so
                # both must be mutated for a refresh to actually take effect.
                self._client.token = fresh.token
                self._client.header = f"{self._client_id}:{fresh.token}"
                if self.streaming is not None:
                    self.streaming.update_token(fresh.token)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(retry_delay)

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        await super().close()
