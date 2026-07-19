from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Union

from brokerkit.models.instrument import Instrument
from brokerkit.models.tick import Tick

# Sync ya async dono callbacks chalte hain
TickCallback = Callable[[Tick], Union[None, Awaitable[None]]]


class StreamingProvider(ABC):

    @abstractmethod
    async def subscribe_ltp(
        self, instruments: list[Instrument], callback: TickCallback
    ) -> None:
        """Har LTP update pe callback(Tick) fire hota hai.

        Connection pehli subscribe pe lazily banta hai. Ek instrument pe
        dobara subscribe karne se uska callback replace ho jaata hai.
        """

    @abstractmethod
    async def unsubscribe_ltp(self, instruments: list[Instrument]) -> None: ...

    @abstractmethod
    async def close(self) -> None:
        """Saari subscriptions hata ke connection chhod do."""
