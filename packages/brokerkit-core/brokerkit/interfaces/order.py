"""The order provider interface."""

from abc import ABC, abstractmethod
from decimal import Decimal

from brokerkit.enums import OrderType, Segment
from brokerkit.models.order import Order, OrderRequest


class OrderProvider(ABC):
    """Places and manages orders.

    ``modify``, ``cancel`` and ``get_order`` take a ``segment`` because
    several brokers require it to locate an order, and it is a core enum
    rather than a broker detail, so passing it leaks nothing broker-specific.

    On a real account, placing orders through the API requires a SEBI-mandated
    registered static IP; without it the write path is rejected while reads
    keep working. Two brokers offer a sandbox that sidesteps this for testing.
    """

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> Order:
        """Submit an order and return the broker\'s initial state for it.

        Many brokers return only an order id here, so the result reflects the
        request with a
        :attr:`~brokerkit.enums.order_status.OrderStatus.PENDING` status.
        Call :meth:`get_order` for the authoritative post-submission state.
        Raises :class:`~brokerkit.exceptions.order.OrderError` if the broker
        rejects it.
        """

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
        """Modify an open order, changing only the fields passed.

        Any field left ``None`` is unchanged. Returns the order\'s state after
        the modification.
        """

    @abstractmethod
    async def cancel(self, order_id: str, segment: Segment) -> Order:
        """Cancel an open order and return its final state.

        Raises :class:`~brokerkit.exceptions.order.OrderError` if the order
        has already executed or been cancelled.
        """

    @abstractmethod
    async def get_order(self, order_id: str, segment: Segment) -> Order:
        """Return the current state of a single order by id."""

    @abstractmethod
    async def list_orders(self) -> list[Order]:
        """Return every order placed today. Empty list if there are none."""
