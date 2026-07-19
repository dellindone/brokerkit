from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Ohlc(BaseModel):
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class DepthLevel(BaseModel):
    price: Decimal
    quantity: int


class Quote(BaseModel):
    last_price: Decimal
    ohlc: Ohlc
    volume: int = 0
    day_change: Decimal | None = None
    day_change_perc: float | None = None
    bid_price: Decimal | None = None
    bid_quantity: int | None = None
    ask_price: Decimal | None = None
    ask_quantity: int | None = None
    buy_depth: list[DepthLevel] = []
    sell_depth: list[DepthLevel] = []
    upper_circuit: Decimal | None = None
    lower_circuit: Decimal | None = None
    open_interest: float | None = None
    average_price: Decimal | None = None
    last_trade_time: datetime | None = None
    