"""Fyers instrument-master provider."""

import asyncio
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from brokerkit.enums import Exchange, InstrumentType, Segment
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

# Public, unauthenticated per-exchange/segment files. Fyers publishes the same
# master as both CSV and JSON; this reads the JSON.
#
# The CSV is positional with no trustworthy header (a Fyers community post flags
# the "official" one as wrong on its trailing columns), so reading it meant
# indexing bare column numbers and it exposed roughly a third of what the master
# actually holds. The JSON names every field, which both removes the guesswork
# and makes series, circuit limits, freeze quantity, face value and the
# has_options/has_futures flags reachable. Verified live 2026-07-22 against real
# rows from NSE_CM, NSE_FO and BSE_CM.
#
# Currency derivatives (NSE_CD) stay excluded: core's Segment enum has no
# CURRENCY value and inventing one is out of scope for an adapter package.
_SOURCES: list[tuple[Exchange, Segment, str]] = [
    (Exchange.NSE, Segment.CASH, "NSE_CM"),
    (Exchange.NSE, Segment.FNO, "NSE_FO"),
    (Exchange.BSE, Segment.CASH, "BSE_CM"),
    (Exchange.BSE, Segment.FNO, "BSE_FO"),
    (Exchange.MCX, Segment.COMMODITY, "MCX_COM"),
]
_JSON_URL = "https://public.fyers.in/sym_details/{name}_sym_master.json"

# Fyers fills absent values with placeholders rather than leaving them out, and
# the placeholder differs by column: "" for text, 0.0 for prices that do not
# apply (an option has no face value), -1.0 for strike on non-options, and "XX"
# for series on anything that is not a cash scrip. Mapped straight through these
# would read as real zeros, so they are collapsed to None.
_EMPTY_TEXT = {"", "XX", "NA"}
_EMPTY_NUMBER = {Decimal("0"), Decimal("-1")}


def _text(value: Any) -> str | None:
    """Return stripped text, or None for Fyers' placeholder spellings."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in _EMPTY_TEXT else text


def _number(value: Any, *, allow_zero: bool = False) -> Decimal | None:
    """Return a Decimal, or None for missing/placeholder numerics.

    ``allow_zero`` is for the few columns where zero is a real reading rather
    than a filler.
    """
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not allow_zero and number in _EMPTY_NUMBER:
        return None
    return number


def _instrument_type(trading_symbol: str, segment: Segment) -> InstrumentType | None:
    """No reliable instrument-type column in the master (``exInstType`` takes
    inconsistent values across files with no clean enum mapping) -- the
    trading-symbol suffix is unambiguous and was verified against real rows
    instead (e.g. "NSE:BANKNIFTY26JUL32500CE").
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
        # -- still ordinary cash instruments, not a distinct core type.
        return InstrumentType.EQ
    return None


def _parse_row(
    row: dict[str, Any],
    exchange: Exchange,
    segment: Segment,
    *,
    include_raw: bool,
) -> Instrument | None:
    _, _, trading_symbol = str(row.get("symTicker", "")).partition(":")
    if not trading_symbol:
        return None
    instrument_type = _instrument_type(trading_symbol, segment)
    if instrument_type is None:
        return None

    isin = _text(row.get("isin"))
    if isin is not None and (len(isin) != 12 or not isin.startswith("IN")):
        isin = None

    expiry_epoch = row.get("expiryDate")
    is_derivative = instrument_type in (InstrumentType.CE, InstrumentType.PE, InstrumentType.FUT)

    return Instrument(
        symbol=trading_symbol,
        exchange=exchange,
        segment=segment,
        instrument_type=instrument_type,
        # symbolDetails is the descriptive name ("BANKNIFTY 28 Jul 26 32500 CE");
        # exSymName repeats the symbol on derivatives, and symDetails drops the
        # underlying ("28 Jul 26 32500 CE"), so neither reads well on its own.
        name=str(row.get("symbolDetails") or row.get("exSymName") or ""),
        isin=isin,
        exchange_token=str(row["exToken"]) if row.get("exToken") is not None else None,
        # Fyers has its own fyToken alongside the exchange token; its API
        # addresses instruments by symbol or fyToken, never by exToken.
        broker_token=str(row["fyToken"]) if row.get("fyToken") is not None else None,
        # Kept verbatim, including the 0 the master reports for indices: an index
        # has no contract size, and substituting 1 would invent a tradeable lot.
        lot_size=int(row["minLotSize"]) if row.get("minLotSize") is not None else 1,
        tick_size=_number(row.get("tickSize")) or Decimal("0.05"),
        expiry=(
            datetime.fromtimestamp(int(expiry_epoch)).date()
            if expiry_epoch not in (None, "", 0)
            else None
        ),
        strike=_number(row.get("strikePrice")),
        underlying=_text(row.get("underSym")) if is_derivative else None,
        series=_text(row.get("exSeries")),
        face_value=_number(row.get("faceValue")),
        freeze_quantity=_number(row.get("qtyFreeze")),
        upper_circuit=_number(row.get("upperPrice")),
        lower_circuit=_number(row.get("lowerPrice")),
        previous_close=_number(row.get("previousClose")),
        # Published as 1/0 rather than a boolean.
        mtf_enabled=bool(row["is_mtf_tradable"]) if row.get("is_mtf_tradable") is not None else None,
        mtf_leverage=_number(row.get("mtf_margin")),
        qty_multiplier=_number(row.get("qtyMultiplier")),
        # Only the cash master carries these; the derivatives files leave them null.
        has_options=row.get("has_options") if isinstance(row.get("has_options"), bool) else None,
        has_futures=row.get("has_futures") if isinstance(row.get("has_futures"), bool) else None,
        raw=dict(row) if include_raw else {},
    )


def _fetch_one(
    exchange: Exchange,
    segment: Segment,
    name: str,
    *,
    instrument_types: frozenset[InstrumentType] | None,
    include_raw: bool,
) -> list[Instrument]:
    response = requests.get(_JSON_URL.format(name=name), timeout=60)
    response.raise_for_status()
    # Keyed by the broker's own ticker; only the values carry the record.
    rows = json.loads(response.text)
    out: list[Instrument] = []
    for row in rows.values():
        try:
            inst = _parse_row(row, exchange, segment, include_raw=include_raw)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            continue
        if inst is None:
            continue
        if instrument_types is not None and inst.instrument_type not in instrument_types:
            continue
        out.append(inst)
    return out


class FyersInstruments(InstrumentProvider):
    """No auth needed -- Fyers' symbol master is public JSON, fetched fresh
    every call (same no-caching contract as the other adapters)."""

    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        wanted_segments = frozenset(segments) if segments is not None else None
        wanted_types = frozenset(instrument_types) if instrument_types is not None else None
        # Fyers splits its master by segment, so a segment filter skips whole
        # downloads rather than parsing and discarding: asking for CASH alone
        # avoids the two derivatives files, which hold the bulk of the rows.
        sources = [
            source
            for source in _SOURCES
            if wanted_segments is None or source[1] in wanted_segments
        ]
        groups = await asyncio.gather(
            *(
                asyncio.to_thread(
                    _fetch_one,
                    exchange,
                    segment,
                    name,
                    instrument_types=wanted_types,
                    include_raw=include_raw,
                )
                for exchange, segment, name in sources
            )
        )
        return [inst for group in groups for inst in group]
