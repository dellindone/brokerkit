"""Angel One streaming provider."""

import asyncio
import inspect
import threading
from collections import defaultdict
from typing import Any

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from brokerkit.exceptions.streaming import StreamingConnectionError, StreamingError
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_angelone.mapper import exchange_type, feed_to_tick

_Key = tuple[int, str]  # (exchangeType int, token str)

# Mode 2 = QUOTE — carries volume_trade_for_the_day + day OHLC (mode 1 = LTP
# wouldn't carry volume), chosen so Tick.volume populates for candle
# bucketing, same call as the Dhan adapter. Mode 3 (SNAP_QUOTE) would add OI
# + depth but isn't needed for the LTP+volume feed contract here.
_QUOTE_MODE = SmartWebSocketV2.QUOTE
_CORRELATION_ID = "brokerkit1"  # 10-char id echoed back on error frames


class AngelStreaming(StreamingProvider):
    """Wraps SmartWebSocketV2. Its connect() calls websocket-client's blocking
    run_forever, so it's run on a daemon thread; parsed packets arrive on
    that thread via the SDK's on_data callback and are bounced to the caller's
    asyncio loop with call_soon_threadsafe — same bridge as GrowwStreaming /
    FyersStreaming.

    Multi-account caveat (documented, guarded): SmartWebSocketV2 keeps
    `input_request_dict` / `current_retry_attempt` as *class* attributes, so
    two instances in one process would share subscription bookkeeping. This
    wrapper shadows both with instance-level attributes right after
    construction to keep accounts isolated — but the SDK's binary parser and
    heartbeat aren't otherwise designed for concurrent sockets, so treat
    two live Angel feeds in one process as unsupported.
    """

    def __init__(self, jwt_token: str, api_key: str, client_code: str, feed_token: str):
        # The two SDK paths disagree about the Bearer prefix, so normalize it
        # here: SmartConnect._request builds `"Bearer {}".format(access_token)`
        # itself (so it stores/expects the RAW jwt), but
        # SmartWebSocketV2.connect() sets `"Authorization": self.auth_token`
        # verbatim with no prefix — meaning the websocket needs an
        # already-prefixed value. (Angel's own samples feed it
        # generateSession's return value, whose `data.jwtToken` the SDK
        # rewrites to "Bearer " + jwt, which is what makes those work.)
        # Passing the raw token straight through would 401 the handshake.
        self._jwt = jwt_token if jwt_token.startswith("Bearer ") else f"Bearer {jwt_token}"
        self._api_key = api_key
        self._client_code = client_code
        self._feed_token = feed_token
        self._sws: SmartWebSocketV2 | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: dict[_Key, TickCallback] = {}
        self._instruments: dict[_Key, Instrument] = {}
        self._ready = asyncio.Event()
        self._connect_error: str | None = None

    @staticmethod
    def _key(inst: Instrument) -> _Key:
        return (exchange_type(inst), str(inst.exchange_token))

    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        for inst in instruments:
            if not inst.exchange_token:
                raise StreamingError(f"{inst.symbol}: exchange_token missing — feed needs it")
        self._loop = asyncio.get_running_loop()
        for inst in instruments:
            key = self._key(inst)
            self._callbacks[key] = callback
            self._instruments[key] = inst

        if self._sws is None:
            await self._connect()

        token_list = _token_list(instruments)
        await asyncio.to_thread(self._sws.subscribe, _CORRELATION_ID, _QUOTE_MODE, token_list)

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._sws is None:
            return
        token_list = _token_list(instruments)
        await asyncio.to_thread(self._sws.unsubscribe, _CORRELATION_ID, _QUOTE_MODE, token_list)
        for inst in instruments:
            key = self._key(inst)
            self._callbacks.pop(key, None)
            self._instruments.pop(key, None)

    async def close(self) -> None:
        if self._sws is None:
            return
        sws, self._sws = self._sws, None
        self._callbacks.clear()
        self._instruments.clear()
        try:
            await asyncio.to_thread(sws.close_connection)
        except Exception:  # noqa: BLE001 — best-effort close
            pass

    async def _connect(self) -> None:
        try:
            sws = SmartWebSocketV2(self._jwt, self._api_key, self._client_code, self._feed_token)
        except Exception as e:  # SDK raises if any token is falsy
            raise StreamingConnectionError(f"Angel feed construction failed: {e}") from e
        # Shadow the SDK's shared *class* attributes with instance-level ones
        # so a second AngelStreaming can't corrupt this one's bookkeeping.
        sws.input_request_dict = {}
        sws.current_retry_attempt = 0
        sws.on_open = self._sdk_on_open
        sws.on_data = self._sdk_on_data
        sws.on_error = self._sdk_on_error
        sws.on_close = self._sdk_on_close
        self._sws = sws
        self._ready.clear()
        self._connect_error = None

        self._thread = threading.Thread(target=sws.connect, daemon=True)
        self._thread.start()

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            raise StreamingConnectionError("Angel feed did not open within 15s") from None
        if self._connect_error is not None:
            raise StreamingConnectionError(self._connect_error)

    # ---- SDK callbacks (fire on the feed's daemon thread) --------------
    def _sdk_on_open(self, _wsapp: Any) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._ready.set)

    def _sdk_on_error(self, _wsapp: Any, error: Any) -> None:
        # If the socket errors before it ever opened, unblock subscribe_ltp
        # with the real message instead of hanging (same fix as the Upstox
        # adapter's connect-hang bug).
        if self._loop is not None and not self._ready.is_set():
            self._connect_error = str(error)
            self._loop.call_soon_threadsafe(self._ready.set)

    def _sdk_on_close(self, _wsapp: Any) -> None:
        pass

    def _sdk_on_data(self, _wsapp: Any, message: Any) -> None:
        if not isinstance(message, dict):
            return
        token = message.get("token")
        exch = message.get("exchange_type")
        if token is None or exch is None:
            return
        key: _Key = (exch, str(token))
        if key not in self._callbacks:
            return
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._dispatch, key, message)

    def _dispatch(self, key: _Key, message: dict) -> None:
        callback = self._callbacks.get(key)
        inst = self._instruments.get(key)
        if callback is None or inst is None:
            return  # unsubscribed between packet and dispatch
        result = callback(feed_to_tick(inst, message))
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)


def _token_list(instruments: list[Instrument]) -> list[dict[str, Any]]:
    """[{"exchangeType": int, "tokens": [str, ...]}] grouped by exchangeType,
    the shape SmartWebSocketV2.subscribe expects."""
    grouped: dict[int, list[str]] = defaultdict(list)
    for inst in instruments:
        grouped[exchange_type(inst)].append(str(inst.exchange_token))
    return [{"exchangeType": et, "tokens": tokens} for et, tokens in grouped.items()]
