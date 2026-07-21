from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class MarketCapAmount(BaseModel):
    value: Decimal
    unit: str
    formatted: str


class CompanyProfile(BaseModel):
    company_profile: str
    sector: str
    sector_market_cap_inr: MarketCapAmount
    sector_market_cap_usd: MarketCapAmount


class FinancialPeriodValue(BaseModel):
    period: str
    value: Decimal


class FinancialLineItem(BaseModel):
    """Shared shape for balance-sheet/cash-flow/income-statement line items
    and their full_statement breakdowns, and for share-holding categories —
    Upstox's fundamentals API reuses this exact {label, history} shape
    across all of them (verified from the SDK's own model files: cash_flow_entry,
    income_statement_entry and share_holding_data are all `{category, history}`,
    and balance/cash-flow/income-statement's own `full_statement` entries are
    `{particular, history}` — same shape, different key name)."""

    label: str
    history: list[FinancialPeriodValue]


class BalanceSheetSummary(BaseModel):
    total_asset: Decimal
    total_liability: Decimal
    period: str


class BalanceSheet(BaseModel):
    statement_type: str
    time_period: str
    units_in: str
    history: list[BalanceSheetSummary]
    full_statement: list[FinancialLineItem] = []


class CashFlow(BaseModel):
    statement_type: str
    time_period: str
    units_in: str
    cash_flow: list[FinancialLineItem]
    full_statement: list[FinancialLineItem] = []


class IncomeStatement(BaseModel):
    statement_type: str
    time_period: str
    units_in: str
    income_statement: list[FinancialLineItem]
    full_statement: list[FinancialLineItem] = []


class KeyRatio(BaseModel):
    name: str
    company_value: Decimal | None = None
    sector_value: Decimal | None = None


class CorporateActionEvent(BaseModel):
    name: str
    value: str


class CorporateAction(BaseModel):
    name: str
    expiry_date: date | None = None
    amount: Decimal | None = None
    ratio: str | None = None
    event_details: list[CorporateActionEvent] = []


class Competitor(BaseModel):
    company_profile: str
    sector: str
    sector_market_cap_inr: MarketCapAmount
    sector_market_cap_usd: MarketCapAmount
    instrument_key: str
