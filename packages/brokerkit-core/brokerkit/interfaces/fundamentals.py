"""The fundamentals provider interface (optional capability)."""

from abc import ABC, abstractmethod

from brokerkit.enums import StatementType
from brokerkit.models.fundamentals import (
    BalanceSheet,
    CashFlow,
    Competitor,
    CompanyProfile,
    CorporateAction,
    FinancialLineItem,
    IncomeStatement,
    KeyRatio,
)
from brokerkit.models.instrument import Instrument


class FundamentalsProvider(ABC):
    """Structured financial data for a listed company, looked up by ISIN.

    Not every broker exposes this — deliberately not an attribute on the
    shared `Broker` base class (see assembly/broker.py); adapters that
    implement it expose it as an extra attribute of their own (e.g.
    `UpstoxBroker.fundamentals`). All methods take an `Instrument` (not a
    raw ISIN string) for consistency with the rest of core's interfaces;
    implementations should raise clearly if `instrument.isin` is None.
    """

    @abstractmethod
    async def get_company_profile(self, instrument: Instrument) -> CompanyProfile:
        """Return the company\'s business profile and sector positioning."""

    @abstractmethod
    async def get_balance_sheet(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> BalanceSheet:
        """Return the balance sheet across reporting periods."""

    @abstractmethod
    async def get_cash_flow(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> CashFlow:
        """Return the cash-flow statement across reporting periods."""

    @abstractmethod
    async def get_income_statement(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> IncomeStatement:
        """Return the income statement across reporting periods."""

    @abstractmethod
    async def get_share_holdings(self, instrument: Instrument) -> list[FinancialLineItem]:
        """Return the shareholding pattern by category over time."""

    @abstractmethod
    async def get_key_ratios(self, instrument: Instrument) -> list[KeyRatio]:
        """Return key financial ratios, each with its sector figure."""

    @abstractmethod
    async def get_corporate_actions(self, instrument: Instrument) -> list[CorporateAction]:
        """Return dividends, splits, bonuses and similar events."""

    @abstractmethod
    async def get_competitors(self, instrument: Instrument) -> list[Competitor]:
        """Return peer companies in the same sector."""
