"""Order placement and management errors."""

from brokerkit.exceptions.common import BrokerKitError


class OrderError(BrokerKitError):
    """An order operation failed.

    Covers placement, modification and cancellation, including a modify or
    cancel aimed at an order that has already executed or been cancelled.
    """


class OrderRejectedError(OrderError):
    """The broker or exchange refused the order.

    Typical causes are price-band violations, freeze quantities, an untradeable
    instrument, or a closed market. BrokerKit deliberately does not
    pre-validate orders against these rules -- brokers are the authority and
    their limits change -- so rejections surface here rather than being
    guessed at client-side.
    """


class InsufficientMarginError(OrderRejectedError):
    """The account lacked the margin to place the order.

    A subclass of :class:`OrderRejectedError`, since it is one specific reason
    for a rejection: ``except OrderRejectedError`` catches both.
    """
