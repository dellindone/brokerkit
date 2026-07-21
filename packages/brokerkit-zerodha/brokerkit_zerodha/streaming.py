"""Zerodha streaming provider."""

import asyncio
import inspect
from typing import Any

from kiteconnect import KiteTicker

from brokerkit.exceptions.streaming import StreamingConnectionError, StreamingError
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_zerodha.mapper import feed_to_tick, instrument_token

# "full" mode, not "quote". Both carry volume, but the 44-byte quote packet
# has NO timestamp field at all (verified in the SDK's _parse_binary — only
# the 184-byte full packet parses exchange_timestamp), and full mode is also
# the only one carrying open interest. Since Tick.timestamp is what candle
# bucketing keys off, quote mode would force synthesizing a client-side
# timestamp — so full mode it is.
_MODE = KiteTicker.MODE_FULL


class ZerodhaStreaming(StreamingProvider):
    """Wraps KiteTicker.

    **The big Kite-specific hazard: KiteTicker runs on the Twisted global
    reactor** (it's built on autobahn/twisted, unlike every other broker's
    feed here, which use websocket-client or a raw socket thread). Two
    consequences that shape this whole class:

    1. **`KiteTicker.stop()` calls `reactor.stop()`, which is irreversible
       and process-wide.** A stopped Twisted reactor cannot be restarted —
       `reactor.run()` afterwards raises ReactorNotRestartable — so calling
       it would permanently break not just this feed but any future Kite feed
       (and anything else using Twisted) in the same process. `close()` here
       therefore calls only `ticker.close()` (which sends the close frame and
       stops the reconnect retries) and never `stop()`. This is deliberate:
       the reactor thread is left alive and idle, which costs nothing.
    2. `connect(threaded=True)` only starts the reactor thread `if not
       reactor.running`, so a second ZerodhaStreaming in the same process
       shares the one reactor rather than hijacking the first connection —
       genuinely better than the Fyers adapter, whose socket class is a hard
       singleton. Multi-account Kite feeds should work; still untested.

    Everything else is easier than the other adapters: KiteTicker parses the
    binary feed itself and hands over ready dicts with prices already
    converted to rupees, so there is no manual struct unpacking and no
    paise scaling here (contrast Groww/Dhan/Angel).

    Callbacks arrive on the reactor thread and are bounced to the caller's
    asyncio loop with call_soon_threadsafe — the same bridge every other
    adapter in this project uses.
    """

    def __init__(self, api_key: str, access_token: str):
        self._api_key = api_key
        self._access_token = access_token
        self._ticker: KiteTicker | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: dict[int, TickCallback] = {}
        self._instruments: dict[int, Instrument] = {}
        self._ready = asyncio.Event()
        self._connect_error: str | None = None

    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        tokens: list[int] = []
        for inst in instruments:
            if not inst.exchange_token:
                raise StreamingError(
                    f"{inst.symbol}: exchange_token missing — the feed needs it"
                )
            tokens.append(instrument_token(inst))

        self._loop = asyncio.get_running_loop()
        for token, inst in zip(tokens, instruments):
            self._callbacks[token] = callback
            self._instruments[token] = inst

        if self._ticker is None:
            await self._connect()

        assert self._ticker is not None
        self._ticker.subscribe(tokens)
        # subscribe() alone leaves the SDK's own bookkeeping at MODE_QUOTE,
        # so the mode must be set explicitly for full packets to arrive.
        self._ticker.set_mode(_MODE, tokens)

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._ticker is None:
            return
        tokens = [instrument_token(i) for i in instruments if i.exchange_token]
        if tokens:
            self._ticker.unsubscribe(tokens)
        for token in tokens:
            self._callbacks.pop(token, None)
            self._instruments.pop(token, None)

    async def close(self) -> None:
        """Closes the socket and stops reconnect retries — but deliberately
        does NOT call `ticker.stop()`, which would stop the process-wide
        Twisted reactor for good (see the class docstring)."""
        if self._ticker is None:
            return
        ticker, self._ticker = self._ticker, None
        self._callbacks.clear()
        self._instruments.clear()
        try:
            ticker.close()
        except Exception:  # noqa: BLE001 — best-effort close
            pass

    async def _connect(self) -> None:
        ticker = KiteTicker(self._api_key, self._access_token)
        ticker.on_connect = self._on_connect
        ticker.on_ticks = self._on_ticks
        ticker.on_error = self._on_error
        ticker.on_close = self._on_close
        self._ticker = ticker
        self._ready.clear()
        self._connect_error = None

        # threaded=True runs the reactor on a daemon thread; without it,
        # reactor.run() would block this coroutine forever.
        ticker.connect(threaded=True)

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            raise StreamingConnectionError("Kite feed did not connect within 15s") from None
        if self._connect_error is not None:
            raise StreamingConnectionError(self._connect_error)

    # ---- KiteTicker callbacks (fire on the Twisted reactor thread) -----
    def _on_connect(self, _ws: Any, _response: Any) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._ready.set)

    def _on_error(self, _ws: Any, code: Any, reason: Any) -> None:
        # If the socket errors before it ever connected, unblock the waiter
        # with the real message instead of hanging until the timeout — the
        # same fix the Upstox adapter needed for its silent connect hang.
        if self._loop is not None and not self._ready.is_set():
            self._connect_error = f"[{code}] {reason}"
            self._loop.call_soon_threadsafe(self._ready.set)

    def _on_close(self, _ws: Any, _code: Any, _reason: Any) -> None:
        pass

    def _on_ticks(self, _ws: Any, ticks: list[dict[str, Any]]) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        for tick in ticks:
            token = tick.get("instrument_token")
            if token in self._callbacks:
                self._loop.call_soon_threadsafe(self._dispatch, token, tick)

    def _dispatch(self, token: int, tick: dict[str, Any]) -> None:
        callback = self._callbacks.get(token)
        inst = self._instruments.get(token)
        if callback is None or inst is None:
            return  # unsubscribed between packet and dispatch
        result = callback(feed_to_tick(inst, tick))
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)
