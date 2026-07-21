"""How long an order stays live."""

from enum import StrEnum


class Validity(StrEnum):
    """The lifetime of an unexecuted order.

    Broker-specific validities with no equivalent here (Zerodha's minute-
    limited TTL, for instance) degrade to :attr:`DAY` when reading orders
    placed elsewhere, since they are still day-scoped.
    """

    DAY = "DAY"
    """Live until the end of the trading day, then cancelled."""

    IOC = "IOC"
    """Immediate-or-cancel: fill whatever can fill now, cancel the rest."""
