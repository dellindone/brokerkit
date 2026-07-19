from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from brokerkit.enums.exchange import Exchange
from brokerkit.enums.segment import Segment
from brokerkit.enums.order_type import OrderType
from brokerkit.enums.transaction_type import TransactionType
from brokerkit.enums.product import Product
from brokerkit.enums.validity import Validity
from brokerkit.enums.order_status import OrderStatus
from brokerkit.models.instrument import Instrument


class OrderRequest(BaseModel):
    instrument: Instrument
    transaction_type: TransactionType
    order_type: OrderType
    quantity: int = Field(gt=0)
    product: Product
    validity: Validity = Validity.DAY
    price: Decimal | None = None          # LIMIT / SL
    trigger_price: Decimal | None = None  # SL / SL_M

    @model_validator(mode="after")
    def _check_prices(self) -> "OrderRequest":
        if self.order_type in (OrderType.LIMIT, OrderType.SL) and self.price is None:
            raise ValueError(f"{self.order_type} order needs price")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and self.trigger_price is None:
            raise ValueError(f"{self.order_type} order needs trigger_price")
        if self.order_type is OrderType.MARKET and (self.price is not None or self.trigger_price is not None):
            raise ValueError("MARKET order must not set price/trigger_price")
        return self


class Order(BaseModel):
    order_id: str
    status: OrderStatus
    trading_symbol: str
    exchange: Exchange
    segment: Segment
    transaction_type: TransactionType
    order_type: OrderType
    product: Product
    validity: Validity
    quantity: int
    filled_quantity: int = 0
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    average_price: Decimal | None = None
    status_message: str | None = None     # broker ka rejection/info text
    created_at: datetime | None = None
    updated_at: datetime | None = None
