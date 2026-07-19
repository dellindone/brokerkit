import asyncio
from decimal import Decimal
from typing import Any, Callable

from growwapi import GrowwAPI

from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.quote import Ohlc, Quote

from brokerkit_groww.errors import groww_errors
from brokerkit_groww.mapper import groww_to_ohlc, groww_to_quote

_BATCH = 50


class GrowwMarketData(MarketDataProvider):

    def __init__(self, client: GrowwAPI) -> None:
        self._client = client

    async def get_quote(self, instrument: Instrument) -> Quote:
        with groww_errors():
            data = await asyncio.to_thread(
                self._client.get_quote,
                trading_symbol=instrument.symbol,
                exchange=instrument.exchange.value,
                segment=instrument.segment.value,
            )
        return groww_to_quote(data)

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        raw = await self._fetch_batched(instruments, self._client.get_ltp)
        return {sym: Decimal(str(v)) for sym, v in raw.items()}

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        raw = await self._fetch_batched(instruments, self._client.get_ohlc)
        return {sym: groww_to_ohlc(v) for sym, v in raw.items()}

    async def _fetch_batched(self, instruments: list[Instrument], sdk_method: Callable) -> dict[str, Any]:
        by_segment: dict[str, list[Instrument]] = {}
        for inst in instruments: by_segment.setdefault(inst.segment.value, []).append(inst)

        out: dict[str, Any] = {}
        for segment, group in by_segment.items():
            for i in range(0, len(group), _BATCH):
                chunk = group[i : i + _BATCH]
                keys = tuple(f"{x.exchange.value}_{x.symbol}" for x in chunk)
                with groww_errors():
                    data = await asyncio.to_thread(sdk_method, exchange_trading_symbols=keys, segment=segment)
                for inst in chunk:
                    v = (data or {}).get(f"{inst.exchange.value}_{inst.symbol}")
                    if v is not None: out[inst.symbol] = v
        return out
    