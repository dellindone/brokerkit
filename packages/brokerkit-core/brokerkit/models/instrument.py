from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

from brokerkit.enums import Exchange, Segment, InstrumentType

class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange: Exchange
    segment: Segment
    instrument_type: InstrumentType
    name: str = ""
    isin: str | None = None
    exchange_token: str | None = None
    lot_size: int = 1
    tick_size: Decimal = Decimal("0.05")
    expiry: date | None = None
    strike: Decimal | None = None
    underlying: str | None = None
