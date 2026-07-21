"""Position holding type."""

from enum import StrEnum


class Product(StrEnum):
    """How long a position is meant to be held, which decides its margining.

    Broker-specific products with no clean equivalent (cover orders, bracket
    orders, margin-trading facility) are mapped onto the nearest of these
    when *reading* orders placed elsewhere, and are never used when placing
    one.
    """

    CNC = "CNC"
    """Delivery. Equity is settled to the demat account."""

    MIS = "MIS"
    """Intraday. Auto-squared off before market close."""

    NRML = "NRML"
    """Carry-forward derivatives position, held on full margin."""
