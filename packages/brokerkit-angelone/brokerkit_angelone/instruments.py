"""Angel One instrument-master provider."""

import asyncio
from typing import Any

import requests

from brokerkit.interfaces.instrument import InstrumentProvider
from brokerkit.models.instrument import Instrument

from brokerkit_angelone.mapper import parse_master_row

# Public, unauthenticated JSON (verified live 2026-07-21: 165,996 rows, HTTP
# 200, ~35 MB). Single combined file across all exchanges — unlike Fyers'
# per-exchange CSVs or Dhan's two-CSV join.
_MASTER_URL = (
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
)


def _fetch_master_rows() -> list[dict[str, Any]]:
    response = requests.get(_MASTER_URL, timeout=90)
    response.raise_for_status()
    return response.json()


async def fetch_master_rows() -> list[dict[str, Any]]:
    """Raw master rows — reused by the market provider's option-chain
    enumeration (Angel has no server-side option-chain endpoint, so the chain
    is built by filtering the master for the underlying's contracts)."""
    return await asyncio.to_thread(_fetch_master_rows)


def _parse(rows: list[dict[str, Any]]) -> list[Instrument]:
    out: list[Instrument] = []
    for row in rows:
        try:
            inst = parse_master_row(row)
        except (ValueError, KeyError):
            continue
        if inst is not None:
            out.append(inst)
    return out


class AngelInstruments(InstrumentProvider):
    """No auth needed — Angel's master is a public JSON file, fetched fresh
    every call (same no-caching contract as every other adapter)."""

    async def fetch_instruments(self) -> list[Instrument]:
        rows = await fetch_master_rows()
        return await asyncio.to_thread(_parse, rows)
