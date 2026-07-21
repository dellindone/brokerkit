"""The instrument provider interface."""

from abc import ABC, abstractmethod

from brokerkit.models.instrument import Instrument


class InstrumentProvider(ABC):
    """Fetches and normalizes a broker\'s tradeable-instrument master."""

    @abstractmethod
    async def fetch_instruments(self) -> list[Instrument]:
        """Download and normalize the broker\'s full instrument master.

        Returns a fresh list on every call -- calling again re-downloads,
        because brokers publish a new master daily. This is a deliberately
        thin operation: implementations fetch, normalize and return, and hold
        no cache, indexes or raw payload afterwards. Storing and querying
        instruments is the application\'s responsibility, not the framework\'s.

        Most brokers serve the master as a public file needing no
        authentication, so this often works before login.
        """
