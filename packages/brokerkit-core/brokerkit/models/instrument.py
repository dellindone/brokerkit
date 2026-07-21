"""The tradeable-instrument model."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from brokerkit.enums import Exchange, InstrumentType, Segment


class Instrument(BaseModel):
    """A single tradeable instrument, normalized across brokers.

    Produced by
    :meth:`~brokerkit.interfaces.instrument.InstrumentProvider.fetch_instruments`
    and passed to nearly every other call, so the adapter always has the
    identifiers its broker needs without the caller having to know them.

    Two things to know before joining these across brokers:

    * ``symbol`` is **not** a cross-broker key. Each broker has its own
      trading symbol for the same contract (``RELIANCE`` vs ``RELIANCE-EQ``;
      ``NIFTY2672123900CE`` vs ``NIFTY-Jul2026-23900-CE``), and orders must
      use the broker's own. Join on ``isin`` for equities, or
      ``exchange_token`` where brokers report real exchange tokens.
    * ``isin`` is ``None`` for every Angel One and Zerodha instrument -- their
      masters have no ISIN column at all -- so those two must be joined on
      ``exchange_token``.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    """The broker's own trading symbol. Broker-specific, not a shared key."""

    exchange: Exchange
    """Exchange the instrument is listed on."""

    segment: Segment
    """Market segment within that exchange."""

    instrument_type: InstrumentType
    """Equity, futures, option or index."""

    name: str = ""
    """Human-readable name, where the broker provides one."""

    isin: str | None = None
    """ISIN, the natural cross-broker key for equities. ``None`` on brokers
    whose master omits it (Angel One, Zerodha) and for derivatives."""

    exchange_token: str | None = None
    """The broker's numeric identifier for this instrument, needed by market
    data and streaming calls. Usually the real exchange token, which matches
    across brokers; Upstox instead stores its own ``instrument_key`` here,
    because every Upstox call addresses instruments that way."""

    lot_size: int = 1
    """Contract size. 1 for equities, the real lot for derivatives."""

    tick_size: Decimal = Decimal("0.05")
    """Minimum price increment, in rupees. Several brokers publish this in
    paise; adapters convert, so this is always rupees."""

    expiry: date | None = None
    """Expiry date. Set for futures and options, ``None`` otherwise."""

    strike: Decimal | None = None
    """Strike price, in rupees. Set for options only."""

    underlying: str | None = None
    """Underlying symbol for derivatives, ``None`` for cash instruments."""
