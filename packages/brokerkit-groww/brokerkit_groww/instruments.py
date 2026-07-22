"""Groww instrument-master provider."""

import asyncio
from collections.abc import Iterable

from growwapi import GrowwAPI

from brokerkit.enums import Exchange, Segment, InstrumentType
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

class GrowwInstruments(InstrumentProvider):
    """Groww instrument-master provider. See
    :class:`~brokerkit.interfaces.instrument.InstrumentProvider`."""
    def __init__(self, client: GrowwAPI):
        self._client = client

    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        # `segments` was already accepted here before the interface grew the
        # parameter, but positionally; it is keyword-only now so every adapter
        # reads the same way.
        wanted_segments = frozenset(segments) if segments is not None else None
        wanted_types = frozenset(instrument_types) if instrument_types is not None else None

        df = await asyncio.to_thread(self._client.get_all_instruments)
        rows = df.where(df.notna(), None)

        out = []
        for row in rows.itertuples(index=False):
            try:
                segment = Segment(row.segment)
            except ValueError:
                continue

            if wanted_segments is not None and segment not in wanted_segments:
                continue

            try:
                instrument_type = InstrumentType(row.instrument_type)
            except ValueError:
                continue
            if wanted_types is not None and instrument_type not in wanted_types:
                continue

            try:
                out.append(Instrument(
                    symbol=row.trading_symbol,
                    exchange=Exchange(row.exchange),
                    segment=segment,
                    instrument_type=instrument_type,
                    name=row.name or "",
                    isin=row.isin if (row.isin and len(row.isin) == 12 and row.isin.startswith("IN")) else None,
                    exchange_token=row.exchange_token,
                    # Groww publishes only the exchange token and addresses
                    # instruments by symbol, so the two coincide here.
                    broker_token=row.exchange_token,
                    lot_size=row.lot_size or 1,
                    tick_size=row.tick_size or "0.05",
                    expiry=row.expiry_date,
                    strike=row.strike_price if row.instrument_type in ("CE", "PE") else None,
                    underlying=row.underlying_symbol,
                    # Groww's master is served as a DataFrame of exactly the
                    # columns mapped above, so there is nothing extra to keep
                    # beyond echoing the row back.
                    raw=dict(row._asdict()) if include_raw else {},
                ))
            except ValueError:
                continue
        self._client.instruments = None
        return out
    