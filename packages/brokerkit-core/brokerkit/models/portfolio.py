"""Demat holding model."""

from decimal import Decimal

from pydantic import BaseModel


class Holding(BaseModel):
    """A long-term holding sitting in the demat account.

    Holdings are demat-level rather than exchange-level, which is why there
    is no exchange field: the same shares can be sold on any exchange they
    are listed on.

    For intraday and derivatives exposure see
    :class:`~brokerkit.models.position.Position` instead.
    """

    trading_symbol: str
    isin: str | None = None
    """ISIN of the held security. Populated by most brokers here even when
    their instrument master omits it."""

    quantity: int
    """Freely sellable quantity."""

    average_price: Decimal
    """Average buy price across the holding."""

    pledged_quantity: int = 0
    """Quantity pledged as collateral, and so not sellable."""

    t1_quantity: int = 0
    """Quantity bought but not yet settled into the demat account."""
