import asyncio
import csv
import io
from datetime import datetime
from decimal import Decimal

import requests

from brokerkit.enums import Exchange, InstrumentType, Segment
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

# Public, unauthenticated per-exchange/segment CSVs — Fyers has no single
# combined download like Groww's one CSV, so we fetch several and
# concatenate. Column semantics aren't documented reliably anywhere
# (a Fyers community post flags the "official" header as wrong on its
# trailing columns) — verified live 2026-07-20 by downloading real rows
# from all five files and cross-checking against the SDK's own
# exch_seg_dict fyToken-prefix convention (e.g. fyToken "1011..." = NSE_FO)
# plus real strike/expiry/CE-PE values. Currency derivatives (NSE_CD) are
# deliberately excluded — core's Segment enum has no CURRENCY value and
# inventing one is out of scope for an adapter package.
_SOURCES: list[tuple[Exchange, Segment, str]] = [
    (Exchange.NSE, Segment.CASH, "NSE_CM"),
    (Exchange.NSE, Segment.FNO, "NSE_FO"),
    (Exchange.BSE, Segment.CASH, "BSE_CM"),
    (Exchange.BSE, Segment.FNO, "BSE_FO"),
    (Exchange.MCX, Segment.COMMODITY, "MCX_COM"),
]
_CSV_URL = "https://public.fyers.in/sym_details/{name}.csv"


def _instrument_type(trading_symbol: str, segment: Segment) -> InstrumentType | None:
    """No reliable numeric instrument-type column in the CSV (the obvious
    candidate column takes inconsistent values across files with no clean
    enum mapping) — the trading-symbol suffix is unambiguous and was
    verified against real rows instead (e.g. "NSE:BANKNIFTY26JUL32500CE").
    """
    if trading_symbol.endswith("-INDEX"):
        return InstrumentType.IDX
    if trading_symbol.endswith("-EQ"):
        return InstrumentType.EQ
    if trading_symbol.endswith("FUT"):
        return InstrumentType.FUT
    if trading_symbol.endswith("CE"):
        return InstrumentType.CE
    if trading_symbol.endswith("PE"):
        return InstrumentType.PE
    if segment == Segment.CASH:
        # NSE's SG/SM/BE/ST/GS series, BSE's -A/-B/-F/-G/-T/-X/-XT groups etc.
        # — still ordinary cash instruments, not a distinct core type.
        return InstrumentType.EQ
    return None


def _parse_row(row: list[str], exchange: Exchange, segment: Segment) -> Instrument | None:
    if len(row) < 16:
        return None
    _, _, trading_symbol = row[9].partition(":")
    if not trading_symbol:
        return None
    instrument_type = _instrument_type(trading_symbol, segment)
    if instrument_type is None:
        return None
    isin = row[5] if row[5] and len(row[5]) == 12 and row[5].startswith("IN") else None
    expiry_epoch = row[8]
    strike = row[15] if len(row) > 15 else ""
    return Instrument(
        symbol=trading_symbol,
        exchange=exchange,
        segment=segment,
        instrument_type=instrument_type,
        name=row[1],
        isin=isin,
        exchange_token=row[12] or None,
        lot_size=int(row[3]) if row[3] else 1,
        tick_size=row[4] or "0.05",
        expiry=datetime.fromtimestamp(int(expiry_epoch)).date() if expiry_epoch else None,
        strike=Decimal(strike) if strike and strike != "-1.0" else None,
        underlying=(
            row[13]
            if instrument_type in (InstrumentType.CE, InstrumentType.PE, InstrumentType.FUT) and len(row) > 13
            else None
        ),
    )


def _fetch_one(exchange: Exchange, segment: Segment, name: str) -> list[Instrument]:
    response = requests.get(_CSV_URL.format(name=name), timeout=30)
    response.raise_for_status()
    out: list[Instrument] = []
    for row in csv.reader(io.StringIO(response.text)):
        try:
            inst = _parse_row(row, exchange, segment)
        except (ValueError, IndexError):
            continue
        if inst is not None:
            out.append(inst)
    return out


class FyersInstruments(InstrumentProvider):
    """No auth needed — Fyers' symbol master is public CSVs, fetched fresh
    every call (same no-caching contract as Groww's adapter)."""

    async def fetch_instruments(self) -> list[Instrument]:
        groups = await asyncio.gather(
            *(
                asyncio.to_thread(_fetch_one, exchange, segment, name)
                for exchange, segment, name in _SOURCES
            )
        )
        return [inst for group in groups for inst in group]
