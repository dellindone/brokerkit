import asyncio
import inspect
from typing import Any

from growwapi import GrowwAPI, GrowwFeed

from brokerkit.exceptions.streaming import StreamingError
from brokerkit.interfaces.streaming import StreamingProvider, TickCallback
from brokerkit.models.instrument import Instrument

from brokerkit_groww.errors import groww_errors
from brokerkit_groww.mapper import groww_to_tick

_Key = tuple[str, str, str]  # (exchange, segment, exchange_token)


class GrowwStreaming(StreamingProvider):

    def __init__(self, client: GrowwAPI) -> None:
        self._client = client
        self._feed: GrowwFeed | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: dict[_Key, TickCallback] = {}
        self._instruments: dict[_Key, Instrument] = {}

    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        for inst in instruments:
            if not inst.exchange_token:
                raise StreamingError(
                    f"{inst.symbol}: exchange_token missing — feed topics need it"
                )
        self._loop = asyncio.get_running_loop()
        if self._feed is None:
            # GrowwFeed ka constructor socket token + websocket kholta hai
            with groww_errors(StreamingError):
                self._feed = await asyncio.to_thread(GrowwFeed, self._client)
        for inst in instruments:
            self._callbacks[self._key(inst)] = callback
            self._instruments[self._key(inst)] = inst
        payload = [self._feed_dict(i) for i in instruments]
        with groww_errors(StreamingError):
            await asyncio.to_thread(
                self._feed.subscribe_ltp, payload, self._on_update
            )

    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        if self._feed is None:
            return
        payload = [self._feed_dict(i) for i in instruments]
        with groww_errors(StreamingError):
            await asyncio.to_thread(self._feed.unsubscribe_ltp, payload)
        for inst in instruments:
            self._callbacks.pop(self._key(inst), None)
            self._instruments.pop(self._key(inst), None)

    async def close(self) -> None:
        if self._feed is None:
            return
        active = list(self._instruments.values())
        if active:
            await self.unsubscribe_ltp(active)
        self._feed = None

    @staticmethod
    def _key(inst: Instrument) -> _Key:
        return (inst.exchange.value, inst.segment.value, inst.exchange_token)

    @staticmethod
    def _feed_dict(inst: Instrument) -> dict[str, str]:
        return {
            "exchange": inst.exchange.value,
            "segment": inst.segment.value,
            "exchange_token": inst.exchange_token,
        }

    def _on_update(self, meta: dict[str, Any]) -> None:
        # NATS ke background thread se aata hai — kaam event loop pe bounce karo
        if not meta or self._loop is None or self._loop.is_closed():
            return
        key: _Key = (
            meta.get("exchange"),
            meta.get("segment"),
            meta.get("feed_key"),
        )
        if key not in self._callbacks:
            return  # sirf active subscriptions ke ticks map hote hain
        self._loop.call_soon_threadsafe(self._dispatch, key)

    def _dispatch(self, key: _Key) -> None:
        callback = self._callbacks.get(key)
        inst = self._instruments.get(key)
        feed = self._feed
        if callback is None or inst is None or feed is None:
            return
        try:
            data = feed.get_ltp()[key[0]][key[1]][key[2]]
        except Exception:
            # unsubscribe race: feed NotSubscribed ya key gayab — tick drop
            return
        if not data:
            return
        result = callback(groww_to_tick(inst, data))
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)
