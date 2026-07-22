"""Dhan instrument-master provider."""

import asyncio
import csv
import io
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from brokerkit.enums import Exchange, InstrumentType, Segment
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

# Public, unauthenticated. dhanhq's own Security.fetch_security_list()
# writes the CSV to disk before reading it back with pandas (verified in
# _security.py) — bypassed here in favor of an in-memory fetch, matching
# every other adapter's no-file-write convention.
#
# BOTH files are needed (real gap, live-verified 2026-07-21): the detailed
# CSV has ISIN/UNDERLYING_SYMBOL but NO exchange trading symbol at all
# (Dhan's own column table confirms SEM_TRADING_SYMBOL is compact-only —
# for equities the ticker leaks into UNDERLYING_SYMBOL, but for options
# that column holds the underlying, so it can't serve as a unique symbol),
# while the compact CSV has SEM_TRADING_SYMBOL but no ISIN/underlying.
# Fetched concurrently and joined on (exchange, segment, security_id).
_DETAILED_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_COMPACT_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

# The `INSTRUMENT` column (NOT `INSTRUMENT_TYPE`, a noisy ~25-value
# exchange-defined set including bonds/ETFs/REITs with no clean core
# mapping) matches the Annexure's Instrument table exactly.
_INSTRUMENT_TYPE = {
    "EQUITY": InstrumentType.EQ,
    "INDEX": InstrumentType.IDX,
    "FUTIDX": InstrumentType.FUT,
    "FUTSTK": InstrumentType.FUT,
    "FUTCOM": InstrumentType.FUT,
    # OPTIDX/OPTSTK/OPTFUT resolved via the OPTION_TYPE column (CE/PE) instead.
}

# Real SEGMENT values (verified live): E/D/M/I/C. Core Segment has no
# INDEX or CURRENCY value — index rows map to CASH (same precedent as
# Fyers' index rows living in its CASH CSV), currency rows (C) are
# excluded entirely (same precedent as Fyers dropping NSE_CD).
_SEGMENT = {
    "E": Segment.CASH,
    "D": Segment.FNO,
    "M": Segment.COMMODITY,
    "I": Segment.CASH,
}

_PLACEHOLDER_DATE = date(1, 1, 1)  # SM_EXPIRY_DATE's "0001-01-01" = "no expiry"

# Dhan's CSV TICK_SIZE is in PAISE, not rupees (live-verified 2026-07-21):
# AMARA RAJA (~₹1093) shows "5.0000" = ₹0.05, SENSEX options "5.0000" = ₹0.05,
# USDINR future "0.2500" = ₹0.0025, GOLD future "100.0000" = ₹1.00, bonds
# "1.0000" = ₹0.01 — every tradeable case confirms ÷100. Without this every
# instrument's tick_size would be 100x too large.
_TICK_PAISE_PER_RUPEE = Decimal("100")


def _decimal_or_none(v: str) -> Decimal | None:
    if not v:
        return None
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return d if d > 0 else None  # STRIKE_PRICE placeholder is "0.00000" / negative for non-options


def _positive_or_none(value: str) -> Decimal | None:
    """Parse a reference column whose "not applicable" filler is zero or negative.

    Dhan does not leave these columns blank; it fills them, and the filler
    differs by column and row (0.0000 on index circuit limits, -1 or 0 on freeze
    quantity). Every one of them measures a price or a quantity, so nothing at or
    below zero is a real reading.
    """
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number > 0 else None


def _parse_row(row: dict[str, str], trading_symbols: dict[tuple[str, str, str], str],
               *, include_raw: bool = False) -> Instrument | None:
    segment = _SEGMENT.get(row["SEGMENT"])
    if segment is None:
        return None  # currency (C) or an unrecognized segment

    instrument = row["INSTRUMENT"]
    option_type = row.get("OPTION_TYPE", "")
    if instrument in ("OPTIDX", "OPTSTK", "OPTFUT"):
        if option_type not in ("CE", "PE"):
            return None
        instrument_type = InstrumentType(option_type)
    else:
        instrument_type = _INSTRUMENT_TYPE.get(instrument)
        if instrument_type is None:
            return None  # FUTCUR/OPTCUR (currency derivatives) etc.

    symbol = trading_symbols.get((row["EXCH_ID"], row["SEGMENT"], row["SECURITY_ID"]))
    if not symbol:
        return None  # not present in the compact master — no usable trading symbol

    isin = row.get("ISIN") or ""
    isin = isin if len(isin) == 12 and isin.startswith("IN") else None

    expiry_raw = row.get("SM_EXPIRY_DATE") or ""
    expiry: date | None = None
    if expiry_raw:
        try:
            expiry = datetime.strptime(expiry_raw[:10], "%Y-%m-%d").date()
        except ValueError:
            expiry = None
        if expiry == _PLACEHOLDER_DATE:
            expiry = None

    lot_size_raw = row.get("LOT_SIZE") or ""
    tick_size_raw = row.get("TICK_SIZE") or ""

    return Instrument(
        symbol=symbol,
        exchange=Exchange(row["EXCH_ID"]),
        segment=segment,
        instrument_type=instrument_type,
        name=row.get("SYMBOL_NAME") or "",
        isin=isin,
        exchange_token=row["SECURITY_ID"],
        # Dhan's SECURITY_ID is the exchange token (RELIANCE 2885) and also
        # what its API takes, so both fields carry it.
        broker_token=row["SECURITY_ID"],
        lot_size=int(float(lot_size_raw)) if lot_size_raw else 1,
        tick_size=(Decimal(tick_size_raw) / _TICK_PAISE_PER_RUPEE) if tick_size_raw else Decimal("0.05"),
        expiry=expiry,
        strike=_decimal_or_none(row.get("STRIKE_PRICE") or ""),
        underlying=row.get("UNDERLYING_SYMBOL") or None,
        # Real codes here are the exchange's own groups -- NSE's EQ/BE/SM, BSE's
        # A/B/X/XT/F/G/M/NS. "NA" is the filler Dhan puts on index rows, which
        # have no series at all.
        series=(series if (series := row.get("SERIES") or "") and series != "NA" else None),
        # Live-verified 2026-07-22: of the cash rows, 13,315 carry a negative
        # SM_FREEZE_QTY and 196 carry zero, against 9,587 real limits. Both are
        # "no freeze limit published", so neither is a quantity.
        freeze_quantity=_positive_or_none(row.get("SM_FREEZE_QTY") or ""),
        # Circuit limits are in RUPEES here, unlike TICK_SIZE in the same file,
        # which is in paise (see _TICK_PAISE_PER_RUPEE). Live-verified
        # 2026-07-22: RELIANCE 1434.0/1173.4 and TCS 2443.2/1999.0 bracket their
        # real prices, so these must not be divided by 100.
        #
        # Non-positive means "no band published": all 191 index rows carry
        # 0.0000/0.0000, since an index has no circuit. One BSE bond row also
        # carries a negative upper limit against a larger lower limit -- that
        # pair is simply corrupt upstream. Only the placeholder is dropped here;
        # cross-field repair is not an adapter's call, so the row's other value
        # passes through as published.
        upper_circuit=_positive_or_none(row.get("SM_UPPER_LIMIT") or ""),
        lower_circuit=_positive_or_none(row.get("SM_LOWER_LIMIT") or ""),
        # Dhan publishes the leverage but no separate eligibility flag; a real
        # multiplier is the only signal that MTF is offered at all.
        mtf_enabled=(mtf_leverage := _positive_or_none(row.get("MTF_LEVERAGE") or "")) is not None,
        mtf_leverage=mtf_leverage,
        raw=dict(row) if include_raw else {},
    )


def _fetch_csv(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def _parse(
    detailed_text: str,
    compact_text: str,
    *,
    segments: frozenset[Segment] | None = None,
    instrument_types: frozenset[InstrumentType] | None = None,
    include_raw: bool = False,
) -> list[Instrument]:
    trading_symbols: dict[tuple[str, str, str], str] = {}
    for row in csv.DictReader(io.StringIO(compact_text)):
        key = (row.get("SEM_EXM_EXCH_ID", ""), row.get("SEM_SEGMENT", ""), row.get("SEM_SMST_SECURITY_ID", ""))
        symbol = row.get("SEM_TRADING_SYMBOL") or ""
        if symbol:
            trading_symbols[key] = symbol

    out: list[Instrument] = []
    for row in csv.DictReader(io.StringIO(detailed_text)):
        try:
            inst = _parse_row(row, trading_symbols, include_raw=include_raw)
        except (ValueError, KeyError):
            continue
        if inst is None:
            continue
        if segments is not None and inst.segment not in segments:
            continue
        if instrument_types is not None and inst.instrument_type not in instrument_types:
            continue
        out.append(inst)
    return out


class DhanInstruments(InstrumentProvider):
    """No auth needed — Dhan's instrument masters are public CSVs, fetched
    fresh every call (same no-caching contract as Groww/Fyers/Upstox)."""

    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        detailed_text, compact_text = await asyncio.gather(
            asyncio.to_thread(_fetch_csv, _DETAILED_CSV_URL),
            asyncio.to_thread(_fetch_csv, _COMPACT_CSV_URL),
        )
        # Both files are single combined downloads covering every segment, so
        # unlike Fyers there is nothing to skip at fetch time -- filtering here
        # can only avoid building Instrument objects, not avoid the transfer.
        return await asyncio.to_thread(
            _parse,
            detailed_text,
            compact_text,
            segments=frozenset(segments) if segments is not None else None,
            instrument_types=frozenset(instrument_types) if instrument_types is not None else None,
            include_raw=include_raw,
        )
