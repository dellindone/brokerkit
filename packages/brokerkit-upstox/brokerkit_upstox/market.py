"""Upstox market-data provider."""

import asyncio
from datetime import date
from decimal import Decimal

from upstox_client import ApiClient, Configuration, MarketQuoteV3Api, OptionsApi

from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain
from brokerkit.models.quote import Ohlc, Quote

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import upstox_key, upstox_to_ohlc, upstox_to_option_chain, upstox_to_quote

# Confirmed from the SDK's own docstrings: up to 500 instrument keys per
# call (well above Groww/Fyers' 50) for both LTP and OHLC.
_BATCH = 500
# "1d" gives get_ohlc() the "today's OHLC so far" semantic that matches
# Groww/Fyers — v3's OHLC endpoint also supports "I1"/"I30" intraday-candle
# intervals, not used here (out of scope for the shared ABC's single-call
# get_ohlc contract).
_OHLC_INTERVAL = "1d"


class UpstoxMarketData(MarketDataProvider):
    """This adapter's real reason to exist (alongside fundamentals/news) —
    gets the most scrutiny, same as Fyers' equivalent file. Works with
    either token type (Analytics Token covers Market Quote/Option Chain
    per Upstox's docs — no OAuth/static-IP needed for this file).
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._quotes = MarketQuoteV3Api(ApiClient(configuration))
        self._options = OptionsApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_quote(self, instrument: Instrument) -> Quote:
        ltp_map = await self._fetch_ltp([instrument])
        ohlc_map = await self._fetch_ohlc([instrument])
        key = upstox_key(instrument)
        ltp_entry = ltp_map.get(key)
        if ltp_entry is None:
            raise BrokerKitError(f"No LTP returned for {instrument.symbol!r}")
        return upstox_to_quote(ltp_entry, ohlc_map.get(key))

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        by_key = await self._fetch_ltp(instruments)
        out: dict[str, Decimal] = {}
        for inst in instruments:
            entry = by_key.get(upstox_key(inst))
            if entry and entry.get("last_price") is not None:
                out[inst.symbol] = Decimal(str(entry["last_price"]))
        return out

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        by_key = await self._fetch_ohlc(instruments)
        out: dict[str, Ohlc] = {}
        for inst in instruments:
            entry = by_key.get(upstox_key(inst))
            if entry:
                out[inst.symbol] = upstox_to_ohlc(entry.get("live_ohlc") or {})
        return out

    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        # strike_count is advisory only — Upstox's endpoint has no such
        # filter and always returns every strike, same limitation Groww has.
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._options.get_put_call_option_chain, upstox_key(underlying), expiry.isoformat()
            )
        rows = [row.to_dict() for row in resp.data or []]
        return upstox_to_option_chain(rows, underlying.symbol, expiry)

    async def _fetch_ltp(self, instruments: list[Instrument]) -> dict[str, dict]:
        return await self._fetch(self._quotes.get_ltp, instruments)

    async def _fetch_ohlc(self, instruments: list[Instrument]) -> dict[str, dict]:
        return await self._fetch(
            lambda **kw: self._quotes.get_market_quote_ohlc(_OHLC_INTERVAL, **kw), instruments
        )

    async def _fetch(self, call, instruments: list[Instrument]) -> dict[str, dict]:
        """Batches/chunks by 500, then re-keys the response by
        `instrument_token` (Upstox's own instrument_key) rather than the
        response dict's own top-level keys — those are "EXCHANGE_SEG:
        TRADINGSYMBOL" strings (verified live against the docs' example),
        a different format from instrument_key and not worth parsing.
        """
        await self._refresh_token()
        out: dict[str, dict] = {}
        for i in range(0, len(instruments), _BATCH):
            chunk = instruments[i : i + _BATCH]
            keys = ",".join(upstox_key(inst) for inst in chunk)
            with upstox_errors():
                resp = await asyncio.to_thread(call, instrument_key=keys)
            data = resp.to_dict().get("data") or {}
            for entry in data.values():
                token = entry.get("instrument_token")
                if token:
                    out[token] = entry
        return out
