import asyncio
import inspect
from typing import Any

from dhanhq import DhanContext, MarketFeed

from brokerkit.exceptions.streaming import StreamingError
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_dhan.mapper import dhan_to_tick, numeric_segment

_Key = tuple[int, int]  # (numeric_exchange_code, security_id_int)

# Quote mode carries volume + OHLC (Ticker mode wouldn't) — see dhan_to_tick.
_QUOTE = MarketFeed.Quote  # 17


class DhanStreaming(StreamingProvider):
    """Wraps dhanhq's MarketFeed (v2 binary feed). MarketFeed runs its own
    event loop in a daemon thread and fires a sync on_message callback per
    parsed packet — bridged to the caller's asyncio loop via
    call_soon_threadsafe, same pattern as GrowwStreaming.

    Constructed lazily on first subscribe: MarketFeed's __init__ calls
    asyncio.set_event_loop() on whatever thread builds it, so it's built
    inside asyncio.to_thread to keep that off the main loop's thread.
    """

    def __init__(self, dhan_context: DhanContext) -> None:
        self._context = dhan_context
        self._feed: MarketFeed | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: dict[_Key, TickCallback] = {}
        self._instruments: dict[_Key, Instrument] = {}

    @staticmethod
    def _key(inst: Instrument) -> _Key:
        return (numeric_segment(inst), int(inst.exchange_token))

    @staticmethod
    def _tuple(inst: Instrument) -> tuple[int, str, int]:
        # MarketFeed wants (numeric_exchange, security_id_str, request_code)
        return (numeric_segment(inst), str(inst.exchange_token), _QUOTE)

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
        tuples = [self._tuple(i) for i in instruments]

        if self._feed is None:
            def _build() -> MarketFeed:
                return MarketFeed(self._context, tuples, version="v2", on_ticks=self._on_message)
            try:
                self._feed = await asyncio.to_thread(_build)
            except Exception as e:  # noqa: BLE001 — surface any feed-construction failure as ours
                raise StreamingError(f"Dhan feed construction failed: {e}") from e
            # .start() spawns the daemon thread running the feed's own loop.
            self._feed.start()
        else:
            # already connected — add on the open socket
            await asyncio.to_thread(self._feed.subscribe_symbols, tuples)

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._feed is None:
            return
        tuples = [self._tuple(i) for i in instruments]
        await asyncio.to_thread(self._feed.unsubscribe_symbols, tuples)
        for inst in instruments:
            key = self._key(inst)
            self._callbacks.pop(key, None)
            self._instruments.pop(key, None)

    async def close(self) -> None:
        if self._feed is None:
            return
        feed, self._feed = self._feed, None
        self._callbacks.clear()
        self._instruments.clear()
        try:
            await asyncio.to_thread(feed.close_connection)
        except Exception:  # noqa: BLE001 — best-effort close
            pass

    def _on_message(self, feed: MarketFeed, data: Any) -> None:
        """Fires on the feed's daemon thread — bounce to the asyncio loop.
        Only Quote packets carry the fields we map; other packet types
        (OI/prev-close/status/disconnect) are ignored here."""
        if not isinstance(data, dict) or data.get("type") != "Quote Data":
            return
        if self._loop is None or self._loop.is_closed():
            return
        key: _Key = (data.get("exchange_segment"), data.get("security_id"))
        if key not in self._callbacks:
            return
        self._loop.call_soon_threadsafe(self._dispatch, key, data)

    def _dispatch(self, key: _Key, data: dict) -> None:
        callback = self._callbacks.get(key)
        inst = self._instruments.get(key)
        if callback is None or inst is None:
            return  # unsubscribed between packet and dispatch
        result = callback(dhan_to_tick(inst, data))
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)
