from decimal import Decimal
from pydantic import BaseModel

from brokerkit.enums import Exchange, Segment

class Instrument(BaseModel):
    symbol: str                # trading symbol, e.g. "RELIANCE"
    exchange: Exchange
    segment: Segment
    name: str = ""
    isin: str | None = None
    instrument_type: str = ""  # EQ / FUT / CE / PE ...
    exchange_token: str | None = None
    lot_size: int = 1
    tick_size: Decimal = Decimal("0.05")
