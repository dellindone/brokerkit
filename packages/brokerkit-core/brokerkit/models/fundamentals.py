"""Company fundamentals models.

Structured financial data -- profiles, statements, ratios, corporate actions
and peers -- returned by
:class:`~brokerkit.interfaces.fundamentals.FundamentalsProvider`.

Not every broker exposes fundamentals; this is an optional capability rather
than part of the shared broker contract.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class MarketCapAmount(BaseModel):
    """A market-capitalisation figure with its unit and display form."""

    value: Decimal
    unit: str
    formatted: str


class CompanyProfile(BaseModel):
    """Business description and sector positioning for a company."""

    company_profile: str
    sector: str
    sector_market_cap_inr: MarketCapAmount
    sector_market_cap_usd: MarketCapAmount


class FinancialPeriodValue(BaseModel):
    """One reporting period's value for a financial line item."""

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
    """Headline totals for one balance-sheet period."""

    total_asset: Decimal
    total_liability: Decimal
    period: str


class BalanceSheet(BaseModel):
    """Balance sheet across reporting periods, with optional full breakdown."""

    statement_type: str
    time_period: str
    units_in: str
    history: list[BalanceSheetSummary]
    full_statement: list[FinancialLineItem] = []


class CashFlow(BaseModel):
    """Cash-flow statement across reporting periods."""

    statement_type: str
    time_period: str
    units_in: str
    cash_flow: list[FinancialLineItem]
    full_statement: list[FinancialLineItem] = []


class IncomeStatement(BaseModel):
    """Income statement across reporting periods."""

    statement_type: str
    time_period: str
    units_in: str
    income_statement: list[FinancialLineItem]
    full_statement: list[FinancialLineItem] = []


class KeyRatio(BaseModel):
    """One financial ratio, with the sector figure for comparison."""

    name: str
    company_value: Decimal | None = None
    sector_value: Decimal | None = None


class CorporateActionEvent(BaseModel):
    """A single detail line attached to a corporate action."""

    name: str
    value: str


class CorporateAction(BaseModel):
    """A dividend, split, bonus or similar company event."""

    name: str
    expiry_date: date | None = None
    amount: Decimal | None = None
    ratio: str | None = None
    event_details: list[CorporateActionEvent] = []


class Competitor(BaseModel):
    """A peer company in the same sector."""

    company_profile: str
    sector: str
    sector_market_cap_inr: MarketCapAmount
    sector_market_cap_usd: MarketCapAmount
    instrument_key: str
