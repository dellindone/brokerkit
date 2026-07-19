import asyncio

from growwapi import GrowwAPI

from brokerkit.enums import Exchange, Segment
from brokerkit.exceptions import InstrumentNotFoundError
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument


class GrowwInstruments(InstrumentProvider):
    def __init__(self, client: GrowwAPI):
        self._client = client
        self._by_symbol: dict[tuple[str, Exchange, Segment], Instrument] = {}
        self._by_token: dict[tuple[str, Exchange, Segment], Instrument] = {}
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        df = await asyncio.to_thread(self._client.get_all_instruments)
        rows = df.where(df.notna(), None).to_dict("records")

        by_symbol, by_token = {}, {}
        for row in rows:
            try:
                instrument = Instrument(
                    symbol=row["trading_symbol"],
                    exchange=Exchange(row["exchange"]),
                    segment=Segment(row["segment"]),
                    name=row["name"] or "",
                    isin=row["isin"],
                    instrument_type=row["instrument_type"] or "",
                    exchange_token=row["exchange_token"],
                    lot_size=row["lot_size"] or 1,
                    tick_size=row["tick_size"] or "0.05",
                )
            except ValueError:
                continue  # exchange/segment outside our enums, or malformed row

            by_symbol[(instrument.symbol.upper(), instrument.exchange, instrument.segment)] = instrument
            if instrument.exchange_token:
                by_token[(instrument.exchange_token, instrument.exchange, instrument.segment)] = instrument

        self._by_symbol, self._by_token = by_symbol, by_token
        self._loaded = True

    async def get_instrument(self, symbol: str, exchange: Exchange, segment: Segment) -> Instrument:
        await self._ensure_loaded()
        try:
            return self._by_symbol[(symbol.upper(), exchange, segment)]
        except KeyError:
            raise InstrumentNotFoundError(f"{symbol} on {exchange}/{segment}") from None

    async def get_by_token(self, exchange_token: str, exchange: Exchange, segment: Segment) -> Instrument:
        await self._ensure_loaded()
        try:
            return self._by_token[(exchange_token, exchange, segment)]
        except KeyError:
            raise InstrumentNotFoundError(f"token {exchange_token} on {exchange}/{segment}") from None

    async def search(self, query: str, limit: int = 20) -> list[Instrument]:
        await self._ensure_loaded()
        q = query.strip().upper()
        if not q:
            return []
        results = []
        for instrument in self._by_symbol.values():
            if q in instrument.symbol.upper() or q in instrument.name.upper():
                results.append(instrument)
                if len(results) >= limit:
                    break
        return results

    async def refresh(self) -> None:
        self._client.instruments = None
        self._loaded = False
        await self._ensure_loaded()
