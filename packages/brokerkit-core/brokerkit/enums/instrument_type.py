"""Instrument classification."""

from enum import StrEnum


class InstrumentType(StrEnum):
    """What kind of instrument this is.

    Brokers disagree on how to express this, so adapters normalize to these
    five values. Two cases worth knowing, because getting them wrong is
    silent rather than loud:

    * Indices are ``IDX`` and are not tradeable. Some brokers do not mark
      them at all -- Zerodha's master labels every index ``EQ`` and only its
      segment column distinguishes them -- so an adapter that trusts the
      broker's own type column would report indices as equities.
    * ``CE``/``PE`` are options and ``FUT`` futures; only these three carry
      :attr:`~brokerkit.models.instrument.Instrument.expiry`, and only
      options carry :attr:`~brokerkit.models.instrument.Instrument.strike`.
    """

    EQ = "EQ"
    """Equity (shares and ETFs)."""

    FUT = "FUT"
    """Futures contract."""

    CE = "CE"
    """Call option."""

    PE = "PE"
    """Put option."""

    IDX = "IDX"
    """Index. Quoted but not tradeable."""
