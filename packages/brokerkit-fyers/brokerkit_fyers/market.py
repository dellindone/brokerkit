"""Fyers market-data provider."""

import asyncio
from datetime import date, datetime, time
from decimal import Decimal

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain
from brokerkit.models.quote import Ohlc, Quote
from brokerkit.utils.datetime import IST

from brokerkit_fyers.errors import check
from brokerkit_fyers.mapper import fyers_symbol, fyers_to_ohlc, fyers_to_option_chain, fyers_to_quote

# Fyers' optionchain `timestamp` param wants the expiry's epoch — verified
# live (decoded real expiryData entries): always 15:30:00 IST on the
# expiry date, not midnight. Computed directly rather than round-tripping
# through an empty-timestamp call first to discover it.
_EXPIRY_CUTOFF = time(15, 30)

# /quotes takes up to 50 comma-separated symbols per call (verified from the
# fyersModel.quotes docstring).
_BATCH = 50


class FyersMarketData(MarketDataProvider):
    """This adapter's real reason to exist — Fyers is the free data source
    behind BrokerKit's roadmap, so this file gets the most scrutiny.
    """

    def __init__(self, client: FyersModel) -> None:
        self._client = client

    async def get_quote(self, instrument: Instrument) -> Quote:
        quotes = await self._fetch_quotes([instrument])
        v = quotes.get(instrument.symbol)
        if v is None:
            raise BrokerKitError(f"No quote returned for {instrument.symbol!r}")
        return fyers_to_quote(v)

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        quotes = await self._fetch_quotes(instruments)
        return {
            symbol: Decimal(str(v["lp"]))
            for symbol, v in quotes.items()
            if v.get("lp") is not None
        }

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        quotes = await self._fetch_quotes(instruments)
        return {symbol: fyers_to_ohlc(v) for symbol, v in quotes.items()}

    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        timestamp = int(datetime.combine(expiry, _EXPIRY_CUTOFF, tzinfo=IST).timestamp())
        resp = await asyncio.to_thread(
            self._client.optionchain,
            {
                "symbol": fyers_symbol(underlying),
                "strikecount": strike_count,
                "timestamp": str(timestamp),
                "greeks": "1",
            },
        )
        check(resp)
        return fyers_to_option_chain(resp.get("data") or {}, underlying.symbol, expiry)

    async def _fetch_quotes(self, instruments: list[Instrument]) -> dict[str, dict]:
        """instrument.symbol (bare) -> the raw "v" object, batched/chunked
        across as many /quotes calls as needed — mirrors Groww's own
        chunk-of-50 batching, just single-segment-free (Fyers' /quotes
        takes mixed exchanges/segments in one call, unlike Groww's
        one-segment-per-call restriction on get_ltp/get_ohlc).
        """
        out: dict[str, dict] = {}
        for i in range(0, len(instruments), _BATCH):
            chunk = instruments[i : i + _BATCH]
            symbols = ",".join(fyers_symbol(inst) for inst in chunk)
            resp = await asyncio.to_thread(self._client.quotes, data={"symbols": symbols})
            check(resp)
            for item in resp.get("d") or []:
                if item.get("s") != "ok":
                    continue
                bare_symbol = item["n"].split(":", 1)[-1]
                out[bare_symbol] = item.get("v") or {}
        return out
