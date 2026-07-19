import asyncio

from growwapi import GrowwAPI

from brokerkit.enums import Exchange, Segment
from brokerkit.exceptions import InstrumentNotFoundError
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument


class GrowwInstruments(InstrumentProvider):
    def __init__(self, client: GrowwAPI):
        self._client = client

    async def fetch_instruments(self) -> list[Instrument]:
        df = await asyncio.to_thread(self._client.get_all_instruments)
        rows = df.where(df.notna(), None)

        out = []

        for row in rows.itertuples(index=False):
            try:
                out.append(Instrument(
                    symbol=row.trading_symbol,
                    exchange=Exchange(row.exchange),
                    segment=Segment(row.segment),
                    name=row.name or "",
                    isin=row.isin,
                    instrument_type=row.instrument_type or "",
                    exchange_token=row.exchange_token,
                    lot_size=row.lot_size or 1,
                    tick_size=row.tick_size or "0.05",
                ))
            except ValueError:
                continue
        self._client.instruments = None
        return out
    