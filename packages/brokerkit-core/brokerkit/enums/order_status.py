from enum import StrEnum

class OrderStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXECUTED = "EXECUTED"
    