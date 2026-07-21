"""Market segments within an exchange."""

from enum import StrEnum


class Segment(StrEnum):
    """The segment an instrument trades in.

    Paired with :class:`~brokerkit.enums.exchange.Exchange` to identify a
    market: ``(NSE, CASH)`` is the NSE equity market, ``(NSE, FNO)`` its
    derivatives market, ``(MCX, COMMODITY)`` commodities.

    Indices are reported under ``CASH`` on their listing exchange, since they
    are quoted there even though they are not tradeable. There is no
    ``CURRENCY`` value, which is why currency derivatives are excluded from
    every adapter's instrument master.
    """

    CASH = "CASH"
    FNO = "FNO"
    COMMODITY = "COMMODITY"
