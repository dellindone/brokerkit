from decimal import Decimal
from pydantic import BaseModel

class Holding(BaseModel):
    trading_symbol: str
    isin: str | None = None
    quantity: int
    average_price: Decimal
    pledged_quantity: int = 0
    t1_quantity: int = 0
