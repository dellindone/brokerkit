"""The streaming provider interface."""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Union

from brokerkit.models.instrument import Instrument
from brokerkit.models.tick import Tick

TickCallback = Callable[[Tick], Union[None, Awaitable[None]]]
"""A tick handler. May be a plain function or a coroutine function -- the
adapter awaits it if it returns an awaitable."""


class StreamingProvider(ABC):
    """Subscribes to a broker\'s live market feed.

    Each broker\'s websocket runs on its own event loop or reactor thread;
    adapters bridge ticks from there onto the caller\'s asyncio loop, so the
    callback always runs where the caller expects. On brokers that charge for
    market data, the feed needs the paid data subscription.
    """

    @abstractmethod
    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        """Subscribe to live ticks and deliver each to ``callback``.

        The connection is opened lazily on the first subscribe. Subscribing
        to an instrument already subscribed replaces its callback. Raises
        :class:`~brokerkit.exceptions.streaming.StreamingConnectionError` if
        the feed cannot be established.
        """

    @abstractmethod
    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None:
        """Stop delivering ticks for the given instruments."""

    @abstractmethod
    async def close(self) -> None:
        """Drop every subscription and close the connection."""
