"""Order request and order state models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from brokerkit.enums.exchange import Exchange
from brokerkit.enums.order_status import OrderStatus
from brokerkit.enums.order_type import OrderType
from brokerkit.enums.product import Product
from brokerkit.enums.segment import Segment
from brokerkit.enums.transaction_type import TransactionType
from brokerkit.enums.validity import Validity
from brokerkit.models.instrument import Instrument


class OrderRequest(BaseModel):
    """An order to place -- what the caller wants, before the broker sees it.

    Deliberately separate from :class:`Order`, which is what the broker
    reports back. The two carry different information: a request has no id,
    no status and no fill data, while an order cannot be re-submitted.

    It carries the whole :class:`~brokerkit.models.instrument.Instrument`
    rather than a symbol, which gives the adapter every identifier its broker
    needs -- symbol, exchange, segment and token -- without reconstructing
    any of them.

    Price fields are validated on construction, so a malformed order fails
    immediately instead of after a network round trip.
    """

    instrument: Instrument
    transaction_type: TransactionType
    order_type: OrderType
    quantity: int = Field(gt=0)
    product: Product
    validity: Validity = Validity.DAY

    price: Decimal | None = None
    """Limit price. Required for LIMIT and SL, forbidden for MARKET."""

    trigger_price: Decimal | None = None
    """Trigger price. Required for SL and SL_M, forbidden for MARKET."""

    @model_validator(mode="after")
    def _check_prices(self) -> "OrderRequest":
        """Enforce the price fields each order type requires."""
        if self.order_type in (OrderType.LIMIT, OrderType.SL) and self.price is None:
            raise ValueError(f"{self.order_type} order needs price")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and self.trigger_price is None:
            raise ValueError(f"{self.order_type} order needs trigger_price")
        if self.order_type is OrderType.LIMIT and self.trigger_price is not None:
            raise ValueError("LIMIT order must not set trigger_price")
        if self.order_type is OrderType.SL_M and self.price is not None:
            raise ValueError("SL_M order must not set price")
        if self.order_type is OrderType.MARKET and (self.price is not None or self.trigger_price is not None):
            raise ValueError("MARKET order must not set price/trigger_price")
        return self


class Order(BaseModel):
    """An order as the broker reports it.

    Flat rather than carrying an
    :class:`~brokerkit.models.instrument.Instrument`, because it is built
    from a broker response that names the instrument rather than describing
    it.

    Many brokers return only an order id when placing an order, so the order
    returned by
    :meth:`~brokerkit.interfaces.order.OrderProvider.place_order` reflects the
    request with a :attr:`~brokerkit.enums.order_status.OrderStatus.PENDING`
    status. Re-read it with ``get_order`` for the authoritative state.
    """

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
    """Quantity ordered."""

    filled_quantity: int = 0
    """Quantity filled so far."""

    price: Decimal | None = None
    trigger_price: Decimal | None = None

    average_price: Decimal | None = None
    """Average price of the filled quantity."""

    status_message: str | None = None
    """The broker's own explanation, typically the rejection reason."""

    created_at: datetime | None = None
    updated_at: datetime | None = None
