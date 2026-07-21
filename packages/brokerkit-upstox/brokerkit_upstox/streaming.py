"""Upstox streaming provider."""

import asyncio
import inspect
from typing import Any

from upstox_client import ApiClient, Configuration, MarketDataStreamerV3

from brokerkit.exceptions.streaming import StreamingConnectionError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_upstox.mapper import upstox_key, upstox_to_tick

_MODE = "full"


class UpstoxStreaming(StreamingProvider):
    """Wraps MarketDataStreamerV3 — a websocket + callback SDK (like
    GrowwFeed/FyersDataSocket), bridged to the event loop the same way.
    One real difference verified from source: `MarketDataStreamerV3.connect()`
    spawns the actual websocket thread (`run_forever`) and returns
    immediately — unlike Fyers' `FyersDataSocket.connect()`, there's no
    guarantee the socket is actually open by the time `connect()` returns.
    Subscribing before it's open would send on a not-yet-ready websocket,
    so this waits for the SDK's own "open" event (via an asyncio.Event
    bridged from the websocket thread) before the first subscribe.

    Uses "full" mode, not "ltpc" — verified from the SDK's own
    MarketDataFeedV3.proto that "ltpc" mode's LTPC message has no
    cumulative-volume field at all (only `ltq`, the size of the single
    most recent trade), unlike Groww/Fyers' basic LTP feeds, which do
    carry real volume. "full" mode's `MarketFullFeed.vtt` (volume traded
    today) and `.oi` (open interest) fill `Tick.volume`/`open_interest`
    properly instead. Trade-off: "full" mode's per-connection instrument
    limit is 2000 (Upstox's documented subscription-limits table), lower
    than "ltpc"'s 5000 — acceptable for the volume this fixes. Index
    instruments use a separate `IndexFullFeed` shape with neither field
    (correct — indices don't trade or carry OI), so `Tick.volume`/
    `open_interest` stay `0`/`None` for those specifically, not a bug.
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration) -> None:
        self._auth = auth
        self._configuration = configuration
        self._streamer: MarketDataStreamerV3 | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None
        self._connect_error: Any = None
        self._callbacks: dict[str, TickCallback] = {}
        self._instruments: dict[str, Instrument] = {}
        self.last_error: Any = None

    async def subscribe_ltp(self, instruments: list[Instrument], callback: TickCallback) -> None:
        self._loop = asyncio.get_running_loop()
        if self._streamer is None:
            token = await self._auth.get_token()
            self._configuration.access_token = token.token
            self._ready = asyncio.Event()
            self._connect_error = None
            self._streamer = MarketDataStreamerV3(ApiClient(self._configuration))
            self._streamer.on("open", self._on_open)
            self._streamer.on("message", self._on_message)
            self._streamer.on("error", self._on_error)
            await asyncio.to_thread(self._streamer.connect)
            await self._ready.wait()
            if self._connect_error is not None:
                error, self._connect_error = self._connect_error, None
                self._streamer = None
                raise StreamingConnectionError(f"Upstox websocket failed to connect: {error}")

        keys = [upstox_key(i) for i in instruments]
        for inst, key in zip(instruments, keys):
            self._callbacks[key] = callback
            self._instruments[key] = inst
        await asyncio.to_thread(self._streamer.subscribe, keys, _MODE)

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._streamer is None:
            return
        keys = [upstox_key(i) for i in instruments]
        await asyncio.to_thread(self._streamer.unsubscribe, keys)
        for key in keys:
            self._callbacks.pop(key, None)
            self._instruments.pop(key, None)

    async def close(self) -> None:
        if self._streamer is None:
            return
        await asyncio.to_thread(self._streamer.disconnect)
        self._streamer = None
        self._callbacks.clear()
        self._instruments.clear()

    def _on_open(self) -> None:
        # Fires on the websocket thread — bounce the Event.set() back to
        # the loop that's awaiting it in subscribe_ltp.
        if self._loop is not None and self._ready is not None:
            self._loop.call_soon_threadsafe(self._ready.set)

    def _on_message(self, data: dict[str, Any]) -> None:
        if not data or self._loop is None or self._loop.is_closed():
            return
        for key, feed in (data.get("feeds") or {}).items():
            if key not in self._callbacks:
                continue  # a since-unsubscribed key — drop
            full_feed = feed.get("fullFeed")
            if full_feed is None:
                continue  # unexpected shape for "full" mode — drop
            # oneof: stocks/derivatives get marketFF (has vtt/oi), indices
            # get indexFF (neither field — real, not a mapping gap).
            market_ff = full_feed.get("marketFF")
            source = market_ff or full_feed.get("indexFF")
            ltpc = source.get("ltpc") if source else None
            if ltpc is None:
                continue
            volume = int(market_ff["vtt"]) if market_ff and market_ff.get("vtt") is not None else 0
            open_interest = float(market_ff["oi"]) if market_ff and market_ff.get("oi") is not None else None
            minute_ohlc = None
            for entry in (source.get("marketOHLC") or {}).get("ohlc") or []:
                if entry.get("interval") == "I1":
                    minute_ohlc = entry
                    break
            self._loop.call_soon_threadsafe(self._dispatch, key, ltpc, volume, open_interest, minute_ohlc)

    def _dispatch(
        self,
        key: str,
        ltpc: dict[str, Any],
        volume: int,
        open_interest: float | None,
        minute_ohlc: dict[str, Any] | None,
    ) -> None:
        callback = self._callbacks.get(key)
        inst = self._instruments.get(key)
        if callback is None or inst is None:
            return
        result = callback(
            upstox_to_tick(inst, ltpc, volume=volume, open_interest=open_interest, minute_ohlc=minute_ohlc)
        )
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)

    def _on_error(self, message: Any) -> None:
        # StreamingProvider has no error callback of its own (matches
        # Groww/Fyers) — stash it for introspection instead of discarding it.
        self.last_error = message
        # If this fires before "open" ever did, subscribe_ltp is still
        # blocked on `_ready.wait()` — without this, a connection failure
        # (bad token, network issue, etc.) hangs forever instead of
        # surfacing an error, since only _on_open used to unblock it.
        if self._loop is not None and self._ready is not None and not self._ready.is_set():
            self._connect_error = message
            self._loop.call_soon_threadsafe(self._ready.set)
