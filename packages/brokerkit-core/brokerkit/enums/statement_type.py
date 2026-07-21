"""Financial statement scope."""

from enum import StrEnum


class StatementType(StrEnum):
    """Whether a financial statement covers the group or the parent alone.

    Used by :class:`~brokerkit.interfaces.fundamentals.FundamentalsProvider`.
    """

    CONSOLIDATED = "consolidated"
    """Parent company plus its subsidiaries."""

    STANDALONE = "standalone"
    """Parent company only."""
