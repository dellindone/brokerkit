"""Groww instrument-master provider."""

import asyncio
from growwapi import GrowwAPI

from brokerkit.enums import Exchange, Segment, InstrumentType
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

class GrowwInstruments(InstrumentProvider):
    """Groww instrument-master provider. See
    :class:`~brokerkit.interfaces.instrument.InstrumentProvider`."""
    def __init__(self, client: GrowwAPI):
        self._client = client

    async def fetch_instruments(self, segments: set[Segment] | None = None) -> list[Instrument]:
        df = await asyncio.to_thread(self._client.get_all_instruments)
        rows = df.where(df.notna(), None)

        out = []
        for row in rows.itertuples(index=False):
            try:
                segment = Segment(row.segment)
            except ValueError:
                continue
            
            if segments is not None and segment not in segments:
                continue

            try:
                out.append(Instrument(
                    symbol=row.trading_symbol,
                    exchange=Exchange(row.exchange),
                    segment=segment,
                    instrument_type=InstrumentType(row.instrument_type),
                    name=row.name or "",
                    isin=row.isin if (row.isin and len(row.isin) == 12 and row.isin.startswith("IN")) else None,
                    exchange_token=row.exchange_token,
                    lot_size=row.lot_size or 1,
                    tick_size=row.tick_size or "0.05",
                    expiry=row.expiry_date,
                    strike=row.strike_price if row.instrument_type in ("CE", "PE") else None,
                    underlying=row.underlying_symbol,
                ))
            except ValueError:
                continue
        self._client.instruments = None
        return out
    