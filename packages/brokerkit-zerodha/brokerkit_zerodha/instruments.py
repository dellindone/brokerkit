"""Zerodha instrument-master provider."""

import asyncio
import csv
import io
from collections.abc import Iterable

import requests

from brokerkit.enums import InstrumentType, Segment
from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

from brokerkit_zerodha.mapper import parse_master_row

# Public, unauthenticated CSV — verified live 2026-07-21: HTTP 200 with no
# Authorization header, ~10 MB, 122,526 rows. `KiteConnect.instruments()`
# would fetch the same file but routes through the authenticated _request
# path, so it is bypassed here: the master is fetched directly, in memory,
# matching every other adapter's no-auth-needed instrument fetch (and
# meaning instruments work before login, which the Dhan/Angel adapters also
# rely on).
_MASTER_URL = "https://api.kite.trade/instruments"

# Kite serves the master without a UA restriction, but a plain UA is sent
# anyway — Upstox's master 403s for some clients without one.
_HEADERS = {"User-Agent": "brokerkit-zerodha"}


def _fetch_master_rows() -> list[dict[str, str]]:
    response = requests.get(_MASTER_URL, headers=_HEADERS, timeout=90)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))


async def fetch_master_rows() -> list[dict[str, str]]:
    """Raw master rows — also used by the market provider's option-chain
    enumeration, since Kite (like Angel) has no server-side option-chain
    endpoint and the chain has to be assembled from the master."""
    return await asyncio.to_thread(_fetch_master_rows)


def _parse(
    rows: list[dict[str, str]],
    *,
    segments: frozenset[Segment] | None = None,
    instrument_types: frozenset[InstrumentType] | None = None,
    include_raw: bool = False,
) -> list[Instrument]:
    out: list[Instrument] = []
    for row in rows:
        try:
            inst = parse_master_row(row)
        except (ValueError, KeyError):
            continue
        if inst is None:
            continue
        if segments is not None and inst.segment not in segments:
            continue
        if instrument_types is not None and inst.instrument_type not in instrument_types:
            continue
        if include_raw:
            # Kite's master has no ISIN and no reference columns beyond what is
            # already mapped, so raw is an echo rather than a source of extras.
            inst = inst.model_copy(update={"raw": dict(row)})
        out.append(inst)
    return out


class ZerodhaInstruments(InstrumentProvider):
    """No auth needed — Kite's master is a public CSV, re-fetched on every
    call (same no-caching contract as every other adapter)."""

    async def fetch_instruments(
        self,
        *,
        segments: Iterable[Segment] | None = None,
        instrument_types: Iterable[InstrumentType] | None = None,
        include_raw: bool = False,
    ) -> list[Instrument]:
        # One combined CSV for every exchange, so filters cannot skip a download.
        rows = await fetch_master_rows()
        return await asyncio.to_thread(
            _parse,
            rows,
            segments=frozenset(segments) if segments is not None else None,
            instrument_types=frozenset(instrument_types) if instrument_types is not None else None,
            include_raw=include_raw,
        )
