"""Dhan market-data provider."""

import asyncio
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import OptionChain, OptionChainStrike, OptionContract, OptionGreeks
from brokerkit.models.quote import DepthLevel, Ohlc, Quote

from brokerkit_dhan.errors import check
from brokerkit_dhan.mapper import _decimal, dhan_segment

# marketfeed endpoints accept up to 1000 instruments/request (docs), keyed
# by exchangeSegment -> list of int security IDs.
_BATCH = 1000


def _body(resp: dict) -> dict:
    """dhanhq double-wraps: DhanHTTP's envelope `data` holds the API's own
    body, which itself has {data, status}. Unwrap both to the inner map,
    which is keyed exchangeSegment -> {security_id_str -> {...}}."""
    inner = check(resp) or {}
    return inner.get("data", inner) or {}


def _group(instruments: list[Instrument]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for inst in instruments:
        grouped[dhan_segment(inst)].append(int(inst.exchange_token))
    return grouped


def _ohlc_from(node: dict[str, Any]) -> Ohlc:
    o = node.get("ohlc") or {}
    z = Decimal("0")
    return Ohlc(
        open=_decimal(o.get("open")) or z,
        high=_decimal(o.get("high")) or z,
        low=_decimal(o.get("low")) or z,
        close=_decimal(o.get("close")) or z,
    )


class DhanMarketData(MarketDataProvider):
    """Dhan market-data provider. See
    :class:`~brokerkit.interfaces.market.MarketDataProvider`."""
    def __init__(self, dhan):
        self._dhan = dhan

    async def _fetch(self, method, instruments: list[Instrument]) -> dict[str, tuple[Instrument, dict]]:
        """Returns {instrument.symbol: (instrument, per-security node)} by
        re-keying Dhan's {segment: {security_id: node}} response back to the
        caller's instruments."""
        by_token = {(dhan_segment(i), str(i.exchange_token)): i for i in instruments}
        out: dict[str, tuple[Instrument, dict]] = {}
        grouped = _group(instruments)
        # respect the 1000-instrument cap by chunking each segment's ids
        for start in range(0, max((len(v) for v in grouped.values()), default=0), _BATCH):
            securities = {seg: ids[start:start + _BATCH] for seg, ids in grouped.items() if ids[start:start + _BATCH]}
            if not securities:
                continue
            resp = await asyncio.to_thread(method, securities)
            body = _body(resp)
            for seg, per_seg in body.items():
                for sec_id, node in (per_seg or {}).items():
                    inst = by_token.get((seg, str(sec_id)))
                    if inst is not None:
                        out[inst.symbol] = (inst, node)
        return out

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        fetched = await self._fetch(self._dhan.ticker_data, instruments)
        return {sym: _decimal(node.get("last_price")) or Decimal("0") for sym, (_, node) in fetched.items()}

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        fetched = await self._fetch(self._dhan.ohlc_data, instruments)
        return {sym: _ohlc_from(node) for sym, (_, node) in fetched.items()}

    async def get_quote(self, instrument: Instrument) -> Quote:
        fetched = await self._fetch(self._dhan.quote_data, [instrument])
        if instrument.symbol not in fetched:
            raise ValueError(f"No quote returned for {instrument.symbol!r}")
        _, node = fetched[instrument.symbol]
        return _dhan_to_quote(node)

    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        resp = await asyncio.to_thread(
            self._dhan.option_chain,
            under_security_id=int(underlying.exchange_token),
            under_exchange_segment=dhan_segment(underlying),
            expiry=expiry.isoformat(),
        )
        body = _body(resp)
        return _dhan_to_option_chain(body, underlying.symbol, expiry)

    async def expiry_list(self, underlying: Instrument) -> list[date]:
        """Dhan-specific helper (not on the shared ABC — no cross-broker
        expiry-list concept in v1): valid expiries for an option-chain
        underlying, needed since get_option_chain requires an exact expiry."""
        resp = await asyncio.to_thread(
            self._dhan.expiry_list,
            under_security_id=int(underlying.exchange_token),
            under_exchange_segment=dhan_segment(underlying),
        )
        body = _body(resp)
        dates = body if isinstance(body, list) else body.get("data", [])
        return [date.fromisoformat(d) for d in dates]


def _dhan_to_quote(node: dict[str, Any]) -> Quote:
    """Full quote node. Depth: Dhan's `buy_quantity`/`sell_quantity` +
    a `depth` list of {price, quantity, orders, ...} per side. Field names
    live-verify TBD; parsed defensively."""
    depth = node.get("depth") or {}
    buy_depth = [
        DepthLevel(price=_decimal(l.get("price")) or Decimal("0"), quantity=int(l.get("quantity") or 0))
        for l in (depth.get("buy") or [])
    ]
    sell_depth = [
        DepthLevel(price=_decimal(l.get("price")) or Decimal("0"), quantity=int(l.get("quantity") or 0))
        for l in (depth.get("sell") or [])
    ]
    return Quote(
        last_price=_decimal(node.get("last_price")) or Decimal("0"),
        ohlc=_ohlc_from(node),
        volume=int(node.get("volume") or 0),
        buy_depth=buy_depth,
        sell_depth=sell_depth,
        bid_price=buy_depth[0].price if buy_depth else None,
        bid_quantity=buy_depth[0].quantity if buy_depth else None,
        ask_price=sell_depth[0].price if sell_depth else None,
        ask_quantity=sell_depth[0].quantity if sell_depth else None,
        open_interest=node.get("oi"),
        upper_circuit=_decimal(node.get("upper_circuit_limit")),
        lower_circuit=_decimal(node.get("lower_circuit_limit")),
        average_price=_decimal(node.get("average_price")),
    )


def _greeks_from(node: dict[str, Any] | None, iv: Any) -> OptionGreeks | None:
    if not node:
        return None
    return OptionGreeks(
        delta=node.get("delta") or 0.0,
        gamma=node.get("gamma") or 0.0,
        theta=node.get("theta") or 0.0,
        vega=node.get("vega") or 0.0,
        iv=float(iv) if iv not in (None, "") else 0.0,
    )


def _contract_from(node: dict[str, Any], strike: Decimal, option_type: str) -> OptionContract:
    from brokerkit.enums import InstrumentType
    return OptionContract(
        symbol="",  # Dhan's option-chain node carries no per-contract symbol
        strike=strike,
        option_type=InstrumentType(option_type),
        ltp=_decimal(node.get("last_price")) or Decimal("0"),
        open_interest=int(node.get("oi") or 0),
        volume=int(node.get("volume") or 0),
        bid_price=_decimal(node.get("top_bid_price")),
        ask_price=_decimal(node.get("top_ask_price")),
        greeks=_greeks_from(node.get("greeks"), node.get("implied_volatility")),
    )


def _dhan_to_option_chain(body: dict[str, Any], underlying_symbol: str, expiry: date) -> OptionChain:
    """`body` = the option-chain payload: {last_price, oc: {strike_str:
    {ce: {...}, pe: {...}}}}. Strike keys are stringified floats like
    "23500.000000"."""
    underlying_ltp = _decimal(body.get("last_price")) or Decimal("0")
    oc = body.get("oc") or {}
    strikes = []
    for strike_str, legs in sorted(oc.items(), key=lambda kv: Decimal(kv[0])):
        strike = Decimal(strike_str)
        ce = legs.get("ce")
        pe = legs.get("pe")
        strikes.append(
            OptionChainStrike(
                strike=strike,
                call=_contract_from(ce, strike, "CE") if ce else None,
                put=_contract_from(pe, strike, "PE") if pe else None,
            )
        )
    return OptionChain(
        underlying_symbol=underlying_symbol,
        underlying_ltp=underlying_ltp,
        expiry=expiry,
        strikes=strikes,
    )
