"""Order lifecycle states."""

from enum import StrEnum


class OrderStatus(StrEnum):
    """Where an order is in its lifecycle.

    Brokers report far more states than these -- between twelve and
    seventeen each -- and every adapter collapses its own vocabulary into
    these six. An unrecognised broker status raises rather than falling back
    to a default, on the grounds that a loud failure beats a silently wrong
    state on an order.

    The distinction that catches people out is :attr:`PENDING` versus
    :attr:`OPEN`, and broker naming is actively misleading about it: Fyers
    calls a live exchange-side order "Pending". Read them by meaning, not by
    the broker's label.
    """

    PENDING = "PENDING"
    """Accepted by the broker but not yet working at the exchange."""

    OPEN = "OPEN"
    """Live at the exchange, waiting to fill. Includes orders whose modify or
    cancel request is still in flight, since the order is still working."""

    EXECUTED = "EXECUTED"
    """Completely filled."""

    CANCELLED = "CANCELLED"
    """Cancelled before filling."""

    REJECTED = "REJECTED"
    """Refused by the broker or the exchange, for example on margin or price
    bands."""

    FAILED = "FAILED"
    """Could not be processed at all."""
