"""Fyers streaming provider."""

import asyncio
import inspect
from typing import Any

from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket

from brokerkit.exceptions.streaming import StreamingError
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_fyers.mapper import fyers_symbol, fyers_to_tick

_DATA_TYPE = "SymbolUpdate"  # LTP-level feed — matches core's LTP-only v1 scope


class FyersStreaming(StreamingProvider):
    """Wraps FyersDataSocket — a thread + callback SDK (like GrowwFeed),
    bridged to the event loop the same way GrowwStreaming does. Two SDK
    quirks verified directly from source that don't exist in the Groww
    adapter:

    1. FyersDataSocket is a process-wide singleton (`__new__` always
       returns the same instance, and `__init__` re-runs on every
       construction call, resetting its access_token and callbacks). A
       second FyersStreaming in the same process — e.g. a second Fyers
       account via BrokerManager — would silently hijack the first one's
       connection. Can't fix that at the adapter layer, only detect and
       fail loudly instead of corrupting another account's stream.
    2. Reconnects (enabled by default in the SDK) wipe FyersDataSocket's
       own subscription bookkeeping (`__on_close` clears
       `scrips_per_channel`/`symbol_token` before reconnecting) — a network
       blip silently kills the stream unless something resubscribes. We
       hook `on_connect` (which the SDK does re-fire after every
       reconnect) to replay our tracked subscriptions.
    """

    _singleton_claimed = False

    def __init__(self, client_id: str, token: str) -> None:
        self._client_id = client_id
        # Raw token only, NOT "client_id:token" — FyersDataSocket decodes
        # this directly as a JWT (access_token_to_hsmtoken splits on "."),
        # unlike FyersModel which needs the compound header form.
        self._token = token
        self._feed: FyersDataSocket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: dict[str, TickCallback] = {}
        self._instruments: dict[str, Instrument] = {}
        self.last_error: Any = None

    def update_token(self, token: str) -> None:
        """Called by FyersBroker's refresh loop. An already-open socket
        doesn't need this mid-session — the HSM token derived at connect
        time is what the live connection actually authenticates with
        (inferred from SDK source, not independently verified against a
        real long-running connection) — this just makes sure a *future*
        reconnect uses a fresh token.
        """
        self._token = token

    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        self._loop = asyncio.get_running_loop()
        if self._feed is None:
            if FyersStreaming._singleton_claimed:
                raise StreamingError(
                    "FyersDataSocket is a process-wide singleton (SDK limitation) — "
                    "a second FyersStreaming instance would hijack the first one's "
                    "connection. Only one Fyers streaming connection is supported per process."
                )
            FyersStreaming._singleton_claimed = True
            self._feed = await asyncio.to_thread(
                FyersDataSocket,
                access_token=self._token,
                on_message=self._on_message,
                on_error=self._on_error,
                on_connect=self._on_connect,
            )
            await asyncio.to_thread(self._feed.connect)

        symbols = [fyers_symbol(i) for i in instruments]
        for inst, sym in zip(instruments, symbols):
            self._callbacks[sym] = callback
            self._instruments[sym] = inst
        await asyncio.to_thread(self._feed.subscribe, symbols, _DATA_TYPE)

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._feed is None:
            return
        symbols = [fyers_symbol(i) for i in instruments]
        await asyncio.to_thread(self._feed.unsubscribe, symbols, _DATA_TYPE)
        for sym in symbols:
            self._callbacks.pop(sym, None)
            self._instruments.pop(sym, None)

    async def close(self) -> None:
        if self._feed is None:
            return
        await asyncio.to_thread(self._feed.close_connection)
        self._feed = None
        self._callbacks.clear()
        self._instruments.clear()
        FyersStreaming._singleton_claimed = False

    def _on_connect(self) -> None:
        # Fires on initial connect AND after every automatic reconnect
        # (verified: __on_close calls back into connect() -> on_open() ->
        # OnOpen()). Just re-queues subscribe messages (thread-safe, no
        # network I/O blocking here) — no need to bounce to the event loop.
        if self._feed is None or not self._callbacks:
            return
        self._feed.subscribe(list(self._callbacks.keys()), _DATA_TYPE)

    def _on_message(self, data: dict[str, Any]) -> None:
        # Fires on FyersDataSocket's own websocket thread — bounce to the loop.
        if not data or self._loop is None or self._loop.is_closed():
            return
        symbol = data.get("symbol")
        if symbol is None or symbol not in self._callbacks:
            return  # index/depth callbacks, or a since-unsubscribed symbol — drop
        self._loop.call_soon_threadsafe(self._dispatch, symbol, data)

    def _dispatch(self, symbol: str, data: dict[str, Any]) -> None:
        callback = self._callbacks.get(symbol)
        inst = self._instruments.get(symbol)
        if callback is None or inst is None:
            return
        result = callback(fyers_to_tick(inst, data))
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)

    def _on_error(self, message: Any) -> None:
        # StreamingProvider has no error callback of its own (matches
        # Groww's adapter — async errors on an active subscription aren't
        # raised synchronously to the caller); stash it for introspection
        # instead of silently discarding it.
        self.last_error = message
