"""Upstox instrument-master provider."""

import asyncio
import gzip
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

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


# Upstox master prices are in paise (see tick_size below).
_TICK_PAISE_PER_RUPEE = Decimal("100")


def _optional_decimal(value) -> Decimal | None:
    """Numeric master columns Upstox simply omits when they do not apply."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_row(row: dict, *, include_raw: bool = False) -> Instrument | None:
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
        # The master publishes both: `exchange_token` is the exchange's own
        # number (RELIANCE 2885, identical at every other broker) and
        # `instrument_key` is Upstox's addressing scheme. They serve different
        # purposes -- one joins, the other calls -- so both are kept.
        exchange_token=str(row["exchange_token"]) if row.get("exchange_token") else None,
        broker_token=row["instrument_key"],
        lot_size=int(row.get("lot_size") or 1),
        # Upstox's tick_size is in PAISE, like Dhan's and Angel One's — caught
        # 2026-07-21 by a cross-broker comparison of the same instruments:
        # Angel/Fyers/Dhan all normalize RELIANCE to Rs 0.10 and a NIFTY option
        # to Rs 0.05, while this adapter was reporting 10.0 and 5.0 (100x too
        # large) straight off the raw master. Three independent brokers
        # agreeing is what settled which side was wrong.
        tick_size=(Decimal(str(row["tick_size"])) / _TICK_PAISE_PER_RUPEE)
        if row.get("tick_size")
        else Decimal("0.05"),
        expiry=datetime.fromtimestamp(expiry_ms / 1000).date() if expiry_ms else None,
        strike=Decimal(str(strike)) if strike else None,
        underlying=row.get("underlying_symbol"),
        # Quantities and multipliers, not prices -- the paise conversion that
        # tick_size needs does not apply to any of these.
        freeze_quantity=_optional_decimal(row.get("freeze_quantity")),
        qty_multiplier=_optional_decimal(row.get("qty_multiplier")),
        security_type=row.get("security_type") or None,
        mtf_enabled=row.get("mtf_enabled") if isinstance(row.get("mtf_enabled"), bool) else None,
        # Upstox calls this "mtf_bracket" and publishes a percentage, where Fyers
        # and Dhan publish multipliers. Carried as-is; see the field's docstring
        # for why cross-broker comparison of this one needs care.
        mtf_leverage=_optional_decimal(row.get("mtf_bracket")),
        raw=dict(row) if include_raw else {},
    )


def _fetch_one(
    url: str,
    *,
    segments: frozenset[Segment] | None = None,
    instrument_types: frozenset[InstrumentType] | None = None,
    include_raw: bool = False,
) -> list[Instrument]:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    response.raise_for_status()
    rows = json.loads(gzip.decompress(response.content))
    out: list[Instrument] = []
    for row in rows:
        try:
            inst = _parse_row(row, include_raw=include_raw)
        except (ValueError, KeyError, TypeError):
            continue
        if inst is None:
            continue
        if segments is not None and inst.segment not in segments:
            continue
        if instrument_types is not None and inst.instrument_type not in instrument_types:
            continue
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

    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        wanted_segments = frozenset(segments) if segments is not None else None
        wanted_types = frozenset(instrument_types) if instrument_types is not None else None
        # Upstox splits its master by EXCHANGE, not by segment, so a segment
        # filter mostly cannot skip a download -- NSE and BSE each carry both
        # cash and derivatives. MCX is the one exception: it is entirely
        # commodity, so it can be skipped outright when commodities are not
        # wanted, which is the common case for an equities caller.
        urls = [
            url
            for exchange, url in _URLS.items()
            if wanted_segments is None
            or exchange is not Exchange.MCX
            or Segment.COMMODITY in wanted_segments
        ]
        groups = await asyncio.gather(
            *(
                asyncio.to_thread(
                    _fetch_one,
                    url,
                    segments=wanted_segments,
                    instrument_types=wanted_types,
                    include_raw=include_raw,
                )
                for url in urls
            )
        )
        return [inst for group in groups for inst in group]
