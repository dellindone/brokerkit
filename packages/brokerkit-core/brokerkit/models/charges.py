from decimal import Decimal

from pydantic import BaseModel


class BrokerageTaxes(BaseModel):
    gst: Decimal
    stt: Decimal
    stamp_duty: Decimal


class OtherCharges(BaseModel):
    transaction: Decimal
    clearing: Decimal
    sebi_turnover: Decimal


class DepositoryPlan(BaseModel):
    name: str
    min_expense: Decimal


class BrokerageCharges(BaseModel):
    total: Decimal
    brokerage: Decimal
    taxes: BrokerageTaxes
    other_charges: OtherCharges
    # Depository Participant charge — applies to delivery sells only, per
    # Upstox's own docs example; unconfirmed live whether it's ever absent
    # for other order shapes, kept optional rather than assumed-present.
    dp_plan: DepositoryPlan | None = None
