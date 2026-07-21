"""Order side."""

from enum import StrEnum


class TransactionType(StrEnum):
    """Which side of the trade an order takes."""

    BUY = "BUY"
    SELL = "SELL"
