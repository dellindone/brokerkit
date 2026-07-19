from decimal import Decimal
from pydantic import BaseModel

from brokerkit.enums import Exchange, Product, Segment


class Position(BaseModel):
    trading_symbol: str
    exchange: Exchange
    segment: Segment
    product: Product
    quantity: int                     
    buy_quantity: int = 0
    buy_price: Decimal | None = None
    sell_quantity: int = 0
    sell_price: Decimal | None = None
    realised_pnl: Decimal | None = None
    isin: str | None = None
