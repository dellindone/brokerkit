from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import InstrumentType


class OptionGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    rho: float | None = None  # not every broker provides this (Fyers doesn't)


class OptionContract(BaseModel):
    symbol: str
    strike: Decimal
    option_type: InstrumentType  # CE or PE
    ltp: Decimal
    open_interest: int = 0
    volume: int = 0
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    greeks: OptionGreeks | None = None


class OptionChainStrike(BaseModel):
    strike: Decimal
    call: OptionContract | None = None
    put: OptionContract | None = None


class OptionChain(BaseModel):
    underlying_symbol: str
    underlying_ltp: Decimal
    expiry: date
    strikes: list[OptionChainStrike]
