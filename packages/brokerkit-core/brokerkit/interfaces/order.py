from abc import ABC, abstractmethod
from decimal import Decimal

from brokerkit.enums import OrderType, Segment
from brokerkit.models.order import Order, OrderRequest


class OrderProvider(ABC):

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> Order:
        """Submit the order; returns the broker's initial Order state."""

    @abstractmethod
    async def modify(
        self,
        order_id: str,
        segment: Segment,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
    ) -> Order:
        """Change only the fields passed; None = leave unchanged."""

    @abstractmethod
    async def cancel(self, order_id: str, segment: Segment) -> Order:
        """Raises OrderError if already executed/cancelled."""

    @abstractmethod
    async def get_order(self, order_id: str, segment: Segment) -> Order: ...

    @abstractmethod
    async def list_orders(self) -> list[Order]: ...
