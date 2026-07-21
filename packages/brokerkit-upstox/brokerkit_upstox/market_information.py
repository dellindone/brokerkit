"""Upstox market-information provider."""

import asyncio
from datetime import date, datetime, time as dtime
from decimal import Decimal
from typing import Any

from upstox_client import ApiClient, Configuration, MarketApi, MarketHolidaysAndTimingsApi

from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.market_information import MarketInformationProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.market_information import (
    ChangeInOiStrike, ChangeInOpenInterest, ExchangeTiming, InstitutionalActivity,
    MarketHoliday, MarketStatus, MaxPain, MaxPainInsight, MtfPrice, MtfSmartlist,
    MtfSmartlistEntry, OiStrike, OpenInterest, Pcr, PcrInsight, Smartlist,
    SmartlistEntry, SmartlistMetric, SmartlistPriceChange,
)

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import epoch_ms_dt, upstox_key

_API_VERSION = "2.0"


def _parse_time(raw: str) -> dtime:
    return datetime.strptime(raw, "%H:%M").time()


def _oi_to_model(data: dict[str, Any]) -> OpenInterest:
    return OpenInterest(
        total_calls=data["total_calls"],
        total_puts=data["total_puts"],
        spot_closing_price=Decimal(str(data["spot_closing_price"])),
        # Verified live 2026-07-21 against a real account: "21-07-2026"
        # (DD-MM-YYYY) — the docs' own rendered example showed ISO
        # "YYYY-MM-DD" instead, which turned out to be wrong/stale. Real
        # response overrides the doc example.
        expiry=datetime.strptime(data["expiry"], "%d-%m-%Y").date(),
        strikes=[
            OiStrike(strike_price=Decimal(str(s["strike_price"])), call_oi=s["call_oi"], put_oi=s["put_oi"])
            for s in data.get("call_put_oi_data_list") or []
        ],
    )


def _change_oi_to_model(data: dict[str, Any]) -> ChangeInOpenInterest:
    return ChangeInOpenInterest(
        total_call_change_oi=data["total_call_change_oi"],
        total_put_change_oi=data["total_put_change_oi"],
        spot_closing_price=Decimal(str(data["spot_closing_price"])),
        expiry=datetime.strptime(data["expiry"], "%d-%m-%Y").date(),  # DD-MM-YYYY, same as get_oi (verified live)
        strikes=[
            ChangeInOiStrike(
                strike_price=Decimal(str(s["strike_price"])),
                call_change_oi=s["call_change_oi"],
                put_change_oi=s["put_change_oi"],
            )
            for s in data.get("call_put_oi_data_list") or []
        ],
    )


def _max_pain_to_model(data: dict[str, Any]) -> MaxPain:
    # expiry_date here is also "DD-MM-YYYY" (verified live, same as
    # get_oi/get_change_in_oi above — turns out all four of these
    # closely-related endpoints agree on this format; only the docs'
    # rendered examples disagreed, and those were wrong for OI/change-OI).
    return MaxPain(
        instrument_key=data["instrument_key"],
        expiry_date=datetime.strptime(data["expiry_date"], "%d-%m-%Y").date(),
        max_pain=Decimal(str(data["max_pain"])),
        spot_closing_price=Decimal(str(data["spot_closing_price"])),
        insights=[
            MaxPainInsight(
                max_pain=Decimal(str(i["max_pain"])),
                spot_price=Decimal(str(i["spot_price"])),
                time=_parse_time(i["time"]),
            )
            for i in data.get("insights") or []
        ],
    )


def _pcr_to_model(data: dict[str, Any]) -> Pcr:
    return Pcr(
        instrument_key=data["instrument_key"],
        expiry_date=datetime.strptime(data["expiry_date"], "%d-%m-%Y").date(),
        pcr=data["pcr"],
        spot_closing_price=Decimal(str(data["spot_closing_price"])),
        insights=[
            PcrInsight(pcr=i["pcr"], spot_price=Decimal(str(i["spot_price"])), time=_parse_time(i["time"]))
            for i in data.get("insights") or []
        ],
    )


def _activity_to_model(item: dict[str, Any]) -> InstitutionalActivity:
    return InstitutionalActivity(
        time_stamp=epoch_ms_dt(item["time_stamp"]),
        buy_amount=Decimal(str(item["buy_amount"])),
        sell_amount=Decimal(str(item["sell_amount"])),
        buy_contracts=item.get("buy_contracts") or 0,
        sell_contracts=item.get("sell_contracts") or 0,
        oi_contracts=item.get("oi_contracts") or 0,
        oi_amount=Decimal(str(item.get("oi_amount") or 0)),
        total_long_contracts=item.get("total_long_contracts") or 0,
        total_short_contracts=item.get("total_short_contracts") or 0,
        total_call_long_contracts=item.get("total_call_long_contracts") or 0,
        total_put_long_contracts=item.get("total_put_long_contracts") or 0,
        total_call_short_contracts=item.get("total_call_short_contracts") or 0,
        total_put_short_contracts=item.get("total_put_short_contracts") or 0,
    )


def _smartlist_to_model(data: dict[str, Any]) -> Smartlist:
    return Smartlist(
        asset_type=data["asset_type"],
        category=data["category"],
        time_stamp=epoch_ms_dt(data["time_stamp"]),
        metric_key=data["metric_key"],
        entries=[
            SmartlistEntry(
                instrument_key=e["instrument_key"],
                price=SmartlistPriceChange(**e["price"]),
                metric=SmartlistMetric(**e["metric"]),
            )
            for e in data.get("smartlist") or []
        ],
        page_number=data["page_number"],
        page_size=data["page_size"],
        total_pages=data["total_pages"],
    )


def _mtf_smartlist_to_model(data: dict[str, Any]) -> MtfSmartlist:
    return MtfSmartlist(
        asset_type=data["asset_type"],
        category=data["category"],
        time_stamp=epoch_ms_dt(data["time_stamp"]),
        metric_key=data["metric_key"],
        entries=[
            MtfSmartlistEntry(
                instrument_key=e["instrument_key"],
                price=MtfPrice(**e["price"]),
                mtf_percent=e["mtf_percent"],
            )
            for e in data.get("smartlist") or []
        ],
        page_number=data["page_number"],
        page_size=data["page_size"],
        total_pages=data["total_pages"],
    )


def _exchange_timing_to_model(d: dict[str, Any]) -> ExchangeTiming:
    return ExchangeTiming(
        exchange=d["exchange"], start_time=epoch_ms_dt(d["start_time"]), end_time=epoch_ms_dt(d["end_time"])
    )


def _holiday_to_model(d: dict[str, Any]) -> MarketHoliday:
    # SDK quirk verified from source (holiday_data.py): the real JSON key is
    # "date", but swagger-codegen renamed the Python-side attribute to
    # `_date` (avoids shadowing the `datetime.date` import in that file) —
    # and to_dict() keys its output by the Python attribute name, not the
    # real JSON key, so it comes back as "_date" here, not "date".
    return MarketHoliday(
        date=d["_date"].date() if isinstance(d["_date"], datetime) else date.fromisoformat(d["_date"]),
        description=d["description"],
        holiday_type=d["holiday_type"],
        closed_exchanges=d.get("closed_exchanges") or [],
        open_exchanges=[_exchange_timing_to_model(e) for e in d.get("open_exchanges") or []],
    )


def _market_status_to_model(d: dict[str, Any]) -> MarketStatus:
    return MarketStatus(exchange=d["exchange"], status=d["status"], last_updated=epoch_ms_dt(d["last_updated"]))


class UpstoxMarketInformation(MarketInformationProvider):
    """Upstox's "Market Information" category — F&O analytics (OI/change-
    in-OI/max-pain/PCR), institutional flows (FII/DII), ranked screeners
    (smartlists), and market calendar/status. Works with either token type
    (Analytics Token explicitly covers "Market Information" per Upstox's
    docs) except `get_holiday`-family calls, which need no auth at all
    (verified from source — same `auth_settings=[]` pattern as historical
    candles).
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._market = MarketApi(ApiClient(configuration))
        self._calendar = MarketHolidaysAndTimingsApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_oi(self, underlying: Instrument, expiry: str, for_date: date) -> OpenInterest:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_oi_data, upstox_key(underlying), expiry, for_date.isoformat()
            )
        return _oi_to_model(resp.to_dict()["data"])

    async def get_change_in_oi(
        self, underlying: Instrument, expiry: str, for_date: date, lookback_days: int
    ) -> ChangeInOpenInterest:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_change_oi_data,
                upstox_key(underlying), expiry, for_date.isoformat(), lookback_days,
            )
        return _change_oi_to_model(resp.to_dict()["data"])

    async def get_max_pain(
        self, underlying: Instrument, expiry: str, for_date: date, bucket_interval_minutes: int
    ) -> MaxPain:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_max_pain_data,
                upstox_key(underlying), expiry, for_date.isoformat(), bucket_interval_minutes,
            )
        return _max_pain_to_model(resp.to_dict()["data"])

    async def get_pcr(
        self, underlying: Instrument, expiry: str, for_date: date, bucket_interval_minutes: int
    ) -> Pcr:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_pcr_data,
                upstox_key(underlying), expiry, for_date.isoformat(), bucket_interval_minutes,
            )
        return _pcr_to_model(resp.to_dict()["data"])

    async def get_fii_activity(
        self, segment: str, interval: str, from_date: date | None = None
    ) -> dict[str, list[InstitutionalActivity]]:
        await self._refresh_token()
        kwargs = {"_from": from_date.isoformat()} if from_date else {}
        with upstox_errors():
            resp = await asyncio.to_thread(self._market.get_fii_data, segment, interval, **kwargs)
        data = resp.to_dict()["data"] or {}
        return {key: [_activity_to_model(item) for item in items] for key, items in data.items()}

    async def get_dii_activity(
        self, interval: str, from_date: date | None = None
    ) -> list[InstitutionalActivity]:
        # Upstox's `data_type` param has exactly one allowed value for DII
        # ("NSE_EQ|CASH") — hardcoded here rather than exposed as a
        # parameter with only one legal choice.
        await self._refresh_token()
        kwargs = {"_from": from_date.isoformat()} if from_date else {}
        with upstox_errors():
            resp = await asyncio.to_thread(self._market.get_dii_data, "NSE_EQ|CASH", interval, **kwargs)
        data = resp.to_dict()["data"] or {}
        items = data.get("NSE_EQ|CASH") or []
        return [_activity_to_model(item) for item in items]

    async def get_futures_smartlist(
        self, asset_type: str, category: str, page_number: int = 1, page_size: int = 50
    ) -> Smartlist:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_smartlist_futures,
                asset_type=asset_type, category=category, page_number=page_number, page_size=page_size,
            )
        return _smartlist_to_model(resp.to_dict()["data"])

    async def get_options_smartlist(
        self, asset_type: str, category: str, page_number: int = 1, page_size: int = 50
    ) -> Smartlist:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_smartlist_options,
                asset_type=asset_type, category=category, page_number=page_number, page_size=page_size,
            )
        return _smartlist_to_model(resp.to_dict()["data"])

    async def get_mtf_smartlist(self, page_number: int = 1, page_size: int = 50) -> MtfSmartlist:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._market.get_smartlist_mtf, page_number=page_number, page_size=page_size
            )
        return _mtf_smartlist_to_model(resp.to_dict()["data"])

    async def get_market_holidays(self) -> list[MarketHoliday]:
        # No auth needed (verified: auth_settings=[]) — deliberately not
        # calling _refresh_token() here.
        with upstox_errors():
            resp = await asyncio.to_thread(self._calendar.get_holidays)
        return [_holiday_to_model(d) for d in resp.to_dict().get("data") or []]

    async def get_exchange_timings(self, for_date: date) -> list[ExchangeTiming]:
        # No auth needed either (same as get_market_holidays).
        with upstox_errors():
            resp = await asyncio.to_thread(self._calendar.get_exchange_timings, for_date.isoformat())
        return [_exchange_timing_to_model(d) for d in resp.to_dict().get("data") or []]

    async def get_market_status(self, exchange: str) -> MarketStatus:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._calendar.get_market_status, exchange)
        return _market_status_to_model(resp.to_dict()["data"])
