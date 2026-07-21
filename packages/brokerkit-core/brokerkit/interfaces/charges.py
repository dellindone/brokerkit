from abc import ABC, abstractmethod
from decimal import Decimal

from brokerkit.enums import Product, TransactionType
from brokerkit.models.charges import BrokerageCharges
from brokerkit.models.instrument import Instrument


class ChargesProvider(ABC):
    """Pre-trade cost calculator — brokerage/taxes/other charges for a
    hypothetical order, without placing it. No Groww/Fyers equivalent, so
    (same call as Fundamentals/News/MarketInformation) this is not on the
    shared `Broker` base class, only on adapters that implement it.
    """

    @abstractmethod
    async def get_brokerage(
        self,
        instrument: Instrument,
        quantity: int,
        product: Product,
        transaction_type: TransactionType,
        price: Decimal,
    ) -> BrokerageCharges: ...
