"""How an order should be priced and triggered."""

from enum import StrEnum


class OrderType(StrEnum):
    """The pricing and triggering rule for an order.

    :class:`~brokerkit.models.order.OrderRequest` validates that the required
    price fields are present for each value, so an incomplete order fails at
    construction rather than at the broker.
    """

    MARKET = "MARKET"
    """Execute at the best available price. Takes neither price nor trigger."""

    LIMIT = "LIMIT"
    """Execute at ``price`` or better. Requires ``price``."""

    SL = "SL"
    """Stop-loss limit: becomes a LIMIT order once ``trigger_price`` is hit.
    Requires both ``price`` and ``trigger_price``."""

    SL_M = "SL_M"
    """Stop-loss market: becomes a MARKET order once ``trigger_price`` is
    hit. Requires ``trigger_price`` only."""
