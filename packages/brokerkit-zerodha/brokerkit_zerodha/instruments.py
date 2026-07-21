"""Zerodha instrument-master provider."""

import asyncio
import csv
import io

import requests

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


def _parse(rows: list[dict[str, str]]) -> list[Instrument]:
    out: list[Instrument] = []
    for row in rows:
        try:
            inst = parse_master_row(row)
        except (ValueError, KeyError):
            continue
        if inst is not None:
            out.append(inst)
    return out


class ZerodhaInstruments(InstrumentProvider):
    """No auth needed — Kite's master is a public CSV, re-fetched on every
    call (same no-caching contract as every other adapter)."""

    async def fetch_instruments(self) -> list[Instrument]:
        rows = await fetch_master_rows()
        return await asyncio.to_thread(_parse, rows)
