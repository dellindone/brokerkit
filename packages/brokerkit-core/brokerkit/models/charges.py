"""Pre-trade cost models."""

from decimal import Decimal

from pydantic import BaseModel


class BrokerageTaxes(BaseModel):
    """Statutory taxes on a trade."""

    gst: Decimal
    """Goods and services tax, charged on brokerage and transaction fees."""

    stt: Decimal
    """Securities transaction tax. Brokers may report the commodities
    equivalent (CTT) in the same field."""

    stamp_duty: Decimal


class OtherCharges(BaseModel):
    """Exchange and regulator fees, separate from brokerage and tax."""

    transaction: Decimal
    """Exchange turnover charge."""

    clearing: Decimal
    """Clearing-member charge. Several brokers fold this into the transaction
    charge rather than itemizing it, in which case it is 0."""

    sebi_turnover: Decimal
    """SEBI turnover fee."""


class DepositoryPlan(BaseModel):
    """Depository participant charge, which applies to delivery sells."""

    name: str
    min_expense: Decimal


class BrokerageCharges(BaseModel):
    """The full cost breakdown for a hypothetical order.

    Returned by
    :meth:`~brokerkit.interfaces.charges.ChargesProvider.get_brokerage`.

    The itemized fields should reconcile to :attr:`total`. That is worth
    asserting when adding a broker: a mismatch means some line item in the
    broker's response is not being mapped, which otherwise shows up as a
    silent zero rather than an error.
    """

    total: Decimal
    """Total cost of the trade, as the broker computes it."""

    brokerage: Decimal
    taxes: BrokerageTaxes
    other_charges: OtherCharges

    dp_plan: DepositoryPlan | None = None
    """Depository charge, where the broker reports one. Typically present
    only for delivery sells."""
