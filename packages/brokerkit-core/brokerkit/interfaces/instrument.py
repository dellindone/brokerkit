"""The instrument provider interface."""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from brokerkit.enums import InstrumentType, Segment
from brokerkit.models.instrument import Instrument


class InstrumentProvider(ABC):
    """Fetches and normalizes a broker's tradeable-instrument master."""

    @abstractmethod
    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        """Download and normalize the broker's instrument master.

        Returns a fresh list on every call -- calling again re-downloads,
        because brokers publish a new master daily. This is a deliberately
        thin operation: implementations fetch, normalize and return, and hold
        no cache or indexes afterwards. Storing and querying instruments is the
        application's responsibility, not the framework's.

        Most brokers serve the master as a public file needing no
        authentication, so this often works before login.

        :param segments: Restrict to these market segments. ``None`` fetches
            every segment the adapter knows. Filtering here rather than in the
            caller lets an adapter skip whole source files: a master runs to
            six figures of rows, most of them derivatives, so a caller after
            cash equities alone should not pay to download and parse the
            options chain.
        :param instrument_types: Restrict to these instrument types, applied
            after parsing. Combine with ``segments`` for the cheapest fetch.
        :param include_raw: Populate :attr:`~brokerkit.models.instrument.Instrument.raw`
            with each broker's own master row. Off by default because it costs
            hundreds of megabytes on a full master; turn it on when you need
            fields brokerkit does not model.

        Filters are a narrowing convenience, not a contract about what exists.
        Asking for a segment a broker does not publish yields no rows rather
        than an error, because "this broker has no commodity master" and "this
        broker has no commodity instruments today" are not usefully different
        to a caller.
        """
