from abc import ABC, abstractmethod

from brokerkit.enums import Exchange, Segment
from brokerkit.models.instrument import Instrument

class InstrumentProvider(ABC):

    @abstractmethod
    async def get_instrument(self, symbol: str, exchange: Exchange, segment: Segment) -> Instrument:
        """Canonical lookup. Raises InstrumentNotFoundError if absent."""
    
    @abstractmethod
    async def get_by_token(self, exchange_token: str, exchange: Exchange, segment: Segment) -> Instrument:
        """Reverse lookup for streaming feeds."""
    
    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[Instrument]:
        """Search for instruments. Returns a list of matching instruments."""
    
    @abstractmethod
    async def refresh(self) -> None:
        """Refresh the instrument cache. Should be called periodically to keep the cache up-to-date."""
