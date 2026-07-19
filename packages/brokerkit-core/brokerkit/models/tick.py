from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import Exchange, Segment


class Tick(BaseModel):
    symbol: str
    exchange: Exchange
    segment: Segment
    ltp: Decimal
    timestamp: datetime | None = None
    volume: int = 0
    open_interest: float | None = None
