"""Upstox fundamentals provider."""

import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from upstox_client import ApiClient, Configuration, FundamentalsApi

from brokerkit.enums import StatementType
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.fundamentals import FundamentalsProvider
from brokerkit.models.fundamentals import (
    BalanceSheet, BalanceSheetSummary, CashFlow, Competitor, CompanyProfile,
    CorporateAction, CorporateActionEvent, FinancialLineItem, FinancialPeriodValue,
    IncomeStatement, KeyRatio, MarketCapAmount,
)
from brokerkit.models.instrument import Instrument

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import upstox_key


def _isin(instrument: Instrument) -> str:
    if not instrument.isin:
        raise BrokerKitError(f"Instrument {instrument.symbol!r} has no ISIN — fundamentals need one")
    return instrument.isin


def _decimal_or_none(v: Any) -> Decimal | None:
    if v is None:
        return None
    # Verified live 2026-07-20: some key-ratio values (e.g. dividend
    # yield/ROE-style ratios) come back as a string with a trailing "%"
    # (e.g. "4.04%") rather than a plain number — stripped here, keeping
    # just the numeric magnitude (same convention as the rest of core's
    # Decimal fields, which carry no separate unit).
    raw = str(v).strip().rstrip("%").strip() if isinstance(v, str) else str(v)
    try:
        return Decimal(raw)
    except InvalidOperation:
        # Anything else non-numeric — surface the actual raw value rather
        # than a bare ConversionSyntax error, so the real shape is known
        # instead of guessed at.
        raise ValueError(f"Upstox fundamentals: could not parse {v!r} as a decimal") from None


def _line_items(raw: list[dict[str, Any]], label_key: str) -> list[FinancialLineItem]:
    """Shared shape across cash_flow/income_statement/share_holdings' own
    entries (keyed "category") and every full_statement breakdown (keyed
    "particular") — see FinancialLineItem's docstring in core.
    """
    return [
        FinancialLineItem(
            label=item[label_key],
            history=[
                FinancialPeriodValue(period=h["period"], value=h["value"])
                for h in item.get("history") or []
            ],
        )
        for item in raw
    ]


def _market_cap(data: dict[str, Any]) -> MarketCapAmount:
    return MarketCapAmount(value=data["value"], unit=data["unit"], formatted=data["formatted"])


class UpstoxFundamentals(FundamentalsProvider):
    """The actual reason this adapter exists, alongside news.py — gets the
    most scrutiny. Works with either token type (Analytics Token covers
    Fundamentals per Upstox's docs).

    Real quirk verified from source (`fundamentals_api.py`): every method
    here takes an `isin` path param EXCEPT `get_competitors`, which takes
    `instrument_key` instead — a genuine API inconsistency, not a typo on
    our side. Also: `.to_dict()` is used throughout rather than attribute
    access, because several of these response `data` fields are typed
    `object` in the swagger spec (verified via the SDK's own swagger_types
    dicts) rather than a concrete model — `.to_dict()` normalizes both
    cases (typed sub-objects and already-raw dict/list) into plain
    dict/list uniformly, so the mapping code below doesn't need to guess
    which case it's in for any given field.
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._client = FundamentalsApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_company_profile(self, instrument: Instrument) -> CompanyProfile:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_company_profile, _isin(instrument))
        data = resp.to_dict()["data"]
        return CompanyProfile(
            company_profile=data["company_profile"],
            sector=data["sector"],
            sector_market_cap_inr=_market_cap(data["sector_market_cap_inr"]),
            sector_market_cap_usd=_market_cap(data["sector_market_cap_usd"]),
        )

    async def get_balance_sheet(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> BalanceSheet:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._client.get_balance_sheet, _isin(instrument),
                type=statement_type.value, fs=include_full_statement,
            )
        data = resp.to_dict()["data"]
        return BalanceSheet(
            statement_type=data["type"],
            time_period=data["time_period"],
            units_in=data["units_in"],
            history=[BalanceSheetSummary(**h) for h in data.get("history") or []],
            full_statement=_line_items(data.get("full_statement") or [], "particular"),
        )

    async def get_cash_flow(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> CashFlow:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._client.get_cash_flow, _isin(instrument),
                type=statement_type.value, fs=include_full_statement,
            )
        data = resp.to_dict()["data"]
        return CashFlow(
            statement_type=data["type"],
            time_period=data["time_period"],
            units_in=data["units_in"],
            cash_flow=_line_items(data.get("cash_flow") or [], "category"),
            full_statement=_line_items(data.get("full_statement") or [], "particular"),
        )

    async def get_income_statement(
        self,
        instrument: Instrument,
        statement_type: StatementType = StatementType.CONSOLIDATED,
        include_full_statement: bool = False,
    ) -> IncomeStatement:
        # Real asymmetry (verified): this endpoint alone also accepts a
        # `time_period` (yearly/quarterly) param that balance_sheet/
        # cash_flow don't expose — not surfaced on the core ABC for v1
        # (YAGNI, matches balance_sheet/cash_flow's own signature); add if
        # a caller actually needs quarterly data.
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._client.get_income_statement, _isin(instrument),
                type=statement_type.value, fs=include_full_statement,
            )
        data = resp.to_dict()["data"]
        return IncomeStatement(
            statement_type=data["type"],
            time_period=data["time_period"],
            units_in=data["units_in"],
            income_statement=_line_items(data.get("income_statement") or [], "category"),
            full_statement=_line_items(data.get("full_statement") or [], "particular"),
        )

    async def get_share_holdings(self, instrument: Instrument) -> list[FinancialLineItem]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_share_holdings, _isin(instrument))
        return _line_items(resp.to_dict().get("data") or [], "category")

    async def get_key_ratios(self, instrument: Instrument) -> list[KeyRatio]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_key_ratios, _isin(instrument))
        return [
            KeyRatio(
                name=item["name"],
                company_value=_decimal_or_none(item.get("company_value")),
                sector_value=_decimal_or_none(item.get("sector_value")),
            )
            for item in resp.to_dict().get("data") or []
        ]

    async def get_corporate_actions(self, instrument: Instrument) -> list[CorporateAction]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_corporate_actions, _isin(instrument))
        out = []
        for item in resp.to_dict().get("data") or []:
            expiry = item.get("expiry_date")
            out.append(CorporateAction(
                name=item["name"],
                # Verified live 2026-07-20: "05 Jun 2026" ("%d %b %Y"), not
                # ISO — the docs don't actually specify a format for this field.
                expiry_date=datetime.strptime(expiry, "%d %b %Y").date() if expiry else None,
                amount=_decimal_or_none(item.get("amount")),
                ratio=item.get("ratio"),
                event_details=[
                    CorporateActionEvent(name=e["name"], value=e["value"])
                    for e in item.get("event_details") or []
                ],
            ))
        return out

    async def get_competitors(self, instrument: Instrument) -> list[Competitor]:
        # The one endpoint keyed by instrument_key, not isin (see class docstring).
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_competitors, upstox_key(instrument))
        return [
            Competitor(
                company_profile=item["company_profile"],
                sector=item["sector"],
                sector_market_cap_inr=_market_cap(item["sector_market_cap_inr"]),
                sector_market_cap_usd=_market_cap(item["sector_market_cap_usd"]),
                instrument_key=item["instrument_key"],
            )
            for item in resp.to_dict().get("data") or []
        ]
