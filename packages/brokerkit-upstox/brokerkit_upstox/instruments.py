import asyncio
import gzip
import json
from datetime import datetime
from decimal import Decimal

import requests

from brokerkit.enums import Exchange, InstrumentType, Segment
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

# Public, unauthenticated per-exchange gzipped JSON files — verified reachable
# live 2026-07-20 (curl with a UA header: 200 + working range-request; a
# community report of 403 did not reproduce). No single combined-and-clean
# file needed — Upstox also publishes complete.json.gz but the per-exchange
# ones are smaller and match Groww/Fyers' per-source fetch pattern.
_URLS = {
    Exchange.NSE: "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    Exchange.BSE: "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
    Exchange.MCX: "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz",
}

# Verified live 2026-07-20 by downloading and inspecting real rows from all
# three files. `segment` values map to core Segment; currency-derivative
# segments (NCD_FO on NSE, BCD_FO on BSE) are deliberately excluded — core's
# Segment enum has no CURRENCY value, same exclusion Fyers made for NSE_CD.
_SEGMENT_MAP = {
    "NSE_EQ": Segment.CASH, "BSE_EQ": Segment.CASH,
    "NSE_INDEX": Segment.CASH, "BSE_INDEX": Segment.CASH,
    "NSE_FO": Segment.FNO, "BSE_FO": Segment.FNO,
    "NSE_COM": Segment.COMMODITY, "MCX_FO": Segment.COMMODITY,
}

# instrument_type raw values, verified against real rows. "COM" only shows
# up on NSE_COM/MCX-underlying rows (e.g. "SILVERMIC") — it's the underlying
# reference entry for that commodity's derivatives, playing the same role
# "INDEX" rows play for equity derivatives, so it maps to IDX too.
_TYPE_MAP = {"EQ": InstrumentType.EQ, "FUT": InstrumentType.FUT, "CE": InstrumentType.CE,
             "PE": InstrumentType.PE, "INDEX": InstrumentType.IDX, "COM": InstrumentType.IDX}


def _instrument_type(raw: str, segment: Segment) -> InstrumentType | None:
    mapped = _TYPE_MAP.get(raw)
    if mapped is not None:
        return mapped
    if segment == Segment.CASH:
        # NSE's SG/SM/BE/ST/GS/N0-N6/TB/GB/BZ series etc. — still ordinary
        # cash instruments (bonds, SME, government securities), not a
        # distinct core type. Same fallback Fyers uses for its own
        # cash-segment "series" letters.
        return InstrumentType.EQ
    return None


def _parse_row(row: dict) -> Instrument | None:
    segment = _SEGMENT_MAP.get(row.get("segment"))
    if segment is None:
        return None
    instrument_type = _instrument_type(row.get("instrument_type", ""), segment)
    if instrument_type is None:
        return None
    expiry_ms = row.get("expiry")
    strike = row.get("strike_price")
    return Instrument(
        symbol=row["trading_symbol"],
        exchange=Exchange(row["exchange"]),
        segment=segment,
        instrument_type=instrument_type,
        name=row.get("name", ""),
        isin=row.get("isin"),
        exchange_token=row["instrument_key"],  # Upstox addresses everything by instrument_key
        lot_size=int(row.get("lot_size") or 1),
        tick_size=Decimal(str(row.get("tick_size") or "0.05")),
        expiry=datetime.fromtimestamp(expiry_ms / 1000).date() if expiry_ms else None,
        strike=Decimal(str(strike)) if strike else None,
        underlying=row.get("underlying_symbol"),
    )


def _fetch_one(url: str) -> list[Instrument]:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    response.raise_for_status()
    rows = json.loads(gzip.decompress(response.content))
    out: list[Instrument] = []
    for row in rows:
        try:
            inst = _parse_row(row)
        except (ValueError, KeyError, TypeError):
            continue
        if inst is not None:
            out.append(inst)
    return out


class UpstoxInstruments(InstrumentProvider):
    """No auth needed — Upstox's instrument master is public gzipped JSON,
    fetched fresh every call (same no-caching contract as Groww/Fyers).
    Every row's `instrument_key` (Upstox's own addressing scheme, e.g.
    "NSE_EQ|INE002A01018") is stashed in `Instrument.exchange_token` — every
    other Upstox provider (market/historical/streaming/news/fundamentals)
    reads it back from there instead of reconstructing it.
    """

    async def fetch_instruments(self) -> list[Instrument]:
        groups = await asyncio.gather(*(asyncio.to_thread(_fetch_one, url) for url in _URLS.values()))
        return [inst for group in groups for inst in group]
