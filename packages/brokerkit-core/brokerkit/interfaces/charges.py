"""The charges provider interface (optional capability)."""

from abc import ABC, abstractmethod
from decimal import Decimal

from brokerkit.enums import Product, TransactionType
from brokerkit.models.charges import BrokerageCharges
from brokerkit.models.instrument import Instrument


class ChargesProvider(ABC):
    """Estimates the full cost of an order without placing it.

    An optional capability -- only some brokers expose a cost calculator --
    so, like fundamentals, news and market information, this is deliberately
    not an attribute on the shared :class:`~brokerkit.assembly.broker.Broker`
    base. Adapters that implement it expose it as their own extra (for
    example ``broker.charges``).
    """

    @abstractmethod
    async def get_brokerage(
        self,
        instrument: Instrument,
        quantity: int,
        product: Product,
        transaction_type: TransactionType,
        price: Decimal,
    ) -> BrokerageCharges:
        """Return the brokerage, taxes and fees for a hypothetical order.

        Nothing is placed. The itemized fields of the result should reconcile
        to its total; when they do not, a line item in the broker\'s response
        is going unmapped.
        """
