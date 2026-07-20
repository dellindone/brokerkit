import asyncio

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.assembly import Broker

from brokerkit_fyers.auth import FyersAuth, REFRESH_INTERVAL
from brokerkit_fyers.instruments import FyersInstruments
from brokerkit_fyers.order import FyersOrderProvider
from brokerkit_fyers.portfolio import FyersPortfolio
from brokerkit_fyers.market import FyersMarketData
from brokerkit_fyers.historical import FyersHistorical
from brokerkit_fyers.streaming import FyersStreaming


class FyersBroker(Broker):
    name = "fyers"

    def __init__(
        self,
        client_id: str,
        secret_key: str,
        pin: str,
        access_token: str,
        refresh_token: str,
    ):
        self.auth = FyersAuth(
            client_id=client_id,
            secret_key=secret_key,
            pin=pin,
            access_token=access_token,
            refresh_token=refresh_token,
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
        pin: str,
        access_token: str,
        refresh_token: str,
    ):
        """Needs a bootstrap access_token + refresh_token obtained once via
        the browser login flow — see login_helper.py / the package README.
        From there this behaves like GrowwBroker.create(): one shared
        client, a background refresh loop, zero fyers_apiv3 imports needed
        in user code.
        """
        broker = cls(
            client_id=client_id,
            secret_key=secret_key,
            pin=pin,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        token = await broker.auth.get_token()
        # is_async=False deliberately, matching Groww's adapter: we wrap
        # the sync client via asyncio.to_thread everywhere rather than use
        # the SDK's own is_async=True mode, whose error-handling paths
        # (FyersServiceAsync) are visibly rougher than the sync ones when
        # reading the source (an undefined-variable risk on some
        # exception branches) — consistency with the rest of the framework
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
        """Unlike Groww's deterministic 6 AM IST expiry, Fyers gives no
        reliable expiry signal — refresh on a fixed conservative interval
        (see auth.REFRESH_INTERVAL) instead of sleeping until a guessed
        timestamp.
        """
        retry_delay = 60
        while True:
            try:
                await asyncio.sleep(REFRESH_INTERVAL.total_seconds())
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
