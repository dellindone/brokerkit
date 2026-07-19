from abc import ABC, abstractmethod

from brokerkit.enums import Exchange, Segment
from brokerkit.models.instrument import Instrument

class InstrumentProvider(ABC):

    @abstractmethod
    async def fetch_instruments(self) -> list[Instrument]:
        """Download and normalize the broker's full instrument master.

        Returns a fresh list on every call (calling again re-downloads —
        brokers update their masters daily). Implementations must not cache
        the result or hold on to the raw payload after normalizing.
        """
    