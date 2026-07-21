import asyncio
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import InstrumentType
from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import (
    OptionChain,
    OptionChainStrike,
    OptionContract,
    OptionGreeks,
)
from brokerkit.models.quote import DepthLevel, Ohlc, Quote
from brokerkit.utils.datetime import IST

from brokerkit_angelone.errors import angel_errors, check
from brokerkit_angelone.instruments import fetch_master_rows
from brokerkit_angelone.mapper import _decimal, _int, to_angel_exchange

# getMarketData accepts up to 50 tokens per request (Angel docs), counted
# across all exchanges in the one call, not per-exchange.
_BATCH = 50


class AngelMarketData(MarketDataProvider):
    def __init__(self, client):
        self._client = client  # shared SmartConnect
        # Lazy per-day cache of the raw master, used ONLY by get_option_chain
        # (Angel has no server-side chain endpoint, so the chain is assembled
        # by filtering the master for the underlying's option contracts).
        # Keyed by fetch date so it self-refreshes daily; never used by the
        # quote/ltp/ohlc paths, which are token-driven.
        self._master_rows: list[dict[str, Any]] | None = None
        self._master_day: date | None = None

    # ---- batch quote helpers -------------------------------------------
    async def _fetch(
        self, mode: str, instruments: list[Instrument]
    ) -> dict[str, tuple[Instrument, dict]]:
        """Returns {instrument.symbol: (instrument, per-security node)},
        re-keying Angel's `data.fetched` list (keyed by its own symbolToken)
        back to the caller's instruments."""
        by_token = {(to_angel_exchange(i), str(i.exchange_token)): i for i in instruments}
        pairs = [(to_angel_exchange(i), str(i.exchange_token)) for i in instruments]
        out: dict[str, tuple[Instrument, dict]] = {}

        for start in range(0, len(pairs), _BATCH):
            chunk = pairs[start : start + _BATCH]
            exchange_tokens: dict[str, list[str]] = defaultdict(list)
            for exch, token in chunk:
                exchange_tokens[exch].append(token)
            with angel_errors():
                resp = await asyncio.to_thread(
                    self._client.getMarketData, mode, dict(exchange_tokens)
                )
            data = check(resp) or {}
            for node in data.get("fetched", []) or []:
                inst = by_token.get((node.get("exchange"), str(node.get("symbolToken"))))
                if inst is not None:
                    out[inst.symbol] = (inst, node)
        return out

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        fetched = await self._fetch("LTP", instruments)
        return {
            sym: _decimal(node.get("ltp")) or Decimal("0")
            for sym, (_, node) in fetched.items()
        }

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        fetched = await self._fetch("OHLC", instruments)
        return {sym: _ohlc_from(node) for sym, (_, node) in fetched.items()}

    async def get_quote(self, instrument: Instrument) -> Quote:
        fetched = await self._fetch("FULL", [instrument])
        if instrument.symbol not in fetched:
            raise ValueError(f"No quote returned for {instrument.symbol!r}")
        _, node = fetched[instrument.symbol]
        return _node_to_quote(node)

    # ---- option chain (assembled — no native endpoint) -----------------
    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        """Angel has no server-side option-chain endpoint, so this is
        assembled: (1) filter the instrument master for the underlying's
        CE/PE contracts at `expiry`, (2) quote them in FULL mode for
        ltp/oi/volume/bid/ask, (3) best-effort merge greeks from Angel's
        `optionGreek` endpoint. Greeks degrade to None if that endpoint
        fails or its strike scaling doesn't line up — the chain still returns
        valid price/OI data. `strike_count` trims to the N nearest strikes on
        each side of the underlying's spot.

        This is the heaviest, least-live-verified path in the adapter (needs
        auth + market hours + the master download); the quote assembly is
        proven but the greeks merge shape is doc-derived — live-tune first
        here if a response contradicts it.
        """
        rows = await self._get_master_rows()
        name = (underlying.name or underlying.symbol).upper()
        contracts = _underlying_options(rows, name, expiry)
        if not contracts:
            raise ValueError(
                f"No option contracts found for {name!r} @ {expiry.isoformat()} "
                "in the Angel master"
            )

        # underlying spot, to center the strike window
        ltp_map = await self.get_ltp([underlying])
        underlying_ltp = ltp_map.get(underlying.symbol) or Decimal("0")
        contracts = _trim_to_window(contracts, underlying_ltp, strike_count)

        option_instruments = [c["instrument"] for c in contracts]
        quotes = await self._fetch("FULL", option_instruments)
        greeks = await self._fetch_greeks(name, expiry)

        by_strike: dict[Decimal, dict[str, OptionContract]] = defaultdict(dict)
        for c in contracts:
            inst = c["instrument"]
            entry = quotes.get(inst.symbol)
            if entry is None:
                continue
            _, node = entry
            side = "call" if inst.instrument_type is InstrumentType.CE else "put"
            by_strike[c["strike"]][side] = _option_contract(
                inst, c["strike"], node, greeks
            )

        strikes = [
            OptionChainStrike(strike=s, call=legs.get("call"), put=legs.get("put"))
            for s, legs in sorted(by_strike.items())
        ]
        return OptionChain(
            underlying_symbol=underlying.symbol,
            underlying_ltp=underlying_ltp,
            expiry=expiry,
            strikes=strikes,
        )

    async def expiry_list(self, underlying: Instrument) -> list[date]:
        """Angel-specific helper (not on the shared ABC — no cross-broker
        expiry-list concept in v1): the distinct option expiries for an
        underlying, read from the master. Handy because get_option_chain
        needs an exact expiry."""
        rows = await self._get_master_rows()
        name = (underlying.name or underlying.symbol).upper()
        expiries: set[date] = set()
        for row in rows:
            if (row.get("name") or "").upper() != name:
                continue
            if not (row.get("instrumenttype") or "").startswith("OPT"):
                continue
            parsed = _parse_master_expiry(row.get("expiry", ""))
            if parsed is not None:
                expiries.add(parsed)
        return sorted(expiries)

    async def _fetch_greeks(
        self, name: str, expiry: date
    ) -> dict[tuple[str, int], dict[str, Any]]:
        """optionGreek(name, expirydate "DDMMMYYYY") -> {(CE/PE, int strike):
        greek node}. Best-effort: any failure yields an empty map so the
        chain still returns without greeks."""
        try:
            params = {"name": name, "expirydate": expiry.strftime("%d%b%Y").upper()}
            with angel_errors():
                resp = await asyncio.to_thread(self._client.optionGreek, params)
            data = check(resp) or []
        except Exception:
            return {}
        out: dict[tuple[str, int], dict[str, Any]] = {}
        for node in data:
            opt_type = (node.get("optionType") or "").upper()
            strike = _decimal(node.get("strikePrice"))
            if opt_type in ("CE", "PE") and strike is not None:
                out[(opt_type, int(strike))] = node
        return out

    async def _get_master_rows(self) -> list[dict[str, Any]]:
        today = datetime.now(IST).date()
        if self._master_rows is None or self._master_day != today:
            self._master_rows = await fetch_master_rows()
            self._master_day = today
        return self._master_rows


# --------------------------------------------------------------------------
# option-chain assembly helpers
# --------------------------------------------------------------------------
_PAISE = Decimal("100")


def _parse_master_expiry(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d%b%Y").date()
    except ValueError:
        return None


def _underlying_options(
    rows: list[dict[str, Any]], name: str, expiry: date
) -> list[dict[str, Any]]:
    """Master rows -> option contracts for (name, expiry), each carrying a
    ready-to-quote Instrument. Imports parse_master_row lazily to avoid a
    module cycle."""
    from brokerkit_angelone.mapper import parse_master_row

    out: list[dict[str, Any]] = []
    for row in rows:
        if (row.get("name") or "").upper() != name:
            continue
        if not (row.get("instrumenttype") or "").startswith("OPT"):
            continue
        if _parse_master_expiry(row.get("expiry", "")) != expiry:
            continue
        inst = parse_master_row(row)
        if inst is None or inst.strike is None:
            continue
        if inst.instrument_type not in (InstrumentType.CE, InstrumentType.PE):
            continue
        out.append({"instrument": inst, "strike": inst.strike})
    return out


def _trim_to_window(
    contracts: list[dict[str, Any]], spot: Decimal, strike_count: int
) -> list[dict[str, Any]]:
    """Keep the `strike_count` nearest distinct strikes on each side of spot
    (so a chain returns ~2*strike_count strikes). If spot is unknown (0),
    keep everything."""
    if spot <= 0 or strike_count <= 0:
        return contracts
    strikes = sorted({c["strike"] for c in contracts})
    below = [s for s in strikes if s <= spot][-strike_count:]
    above = [s for s in strikes if s > spot][:strike_count]
    keep = set(below) | set(above)
    return [c for c in contracts if c["strike"] in keep]


def _option_contract(
    instrument: Instrument,
    strike: Decimal,
    node: dict[str, Any],
    greeks: dict[tuple[str, int], dict[str, Any]],
) -> OptionContract:
    depth = node.get("depth") or {}
    buy = _levels(depth.get("buy"))  # zero-padding dropped — see _levels
    sell = _levels(depth.get("sell"))
    opt_type = instrument.instrument_type.value  # "CE" / "PE"
    # optionGreek keys on a rupee-denominated `strikePrice` ("24200.000000"),
    # matching the master's strike after its ÷100 — live-confirmed, so an int
    # comparison lines the two up exactly.
    greek_node = greeks.get((opt_type, int(strike)))
    return OptionContract(
        symbol=instrument.symbol,
        strike=strike,
        option_type=instrument.instrument_type,
        ltp=_decimal(node.get("ltp")) or Decimal("0"),
        open_interest=_int(node.get("opnInterest")),
        volume=_int(node.get("tradeVolume")),
        bid_price=buy[0].price if buy else None,
        ask_price=sell[0].price if sell else None,
        greeks=_greeks_from(greek_node),
    )


def _greeks_from(node: dict[str, Any] | None) -> OptionGreeks | None:
    if not node:
        return None
    return OptionGreeks(
        delta=_float(node.get("delta")),
        gamma=_float(node.get("gamma")),
        theta=_float(node.get("theta")),
        vega=_float(node.get("vega")),
        iv=_float(node.get("impliedVolatility")),
        rho=None,  # optionGreek doesn't return rho
    )


# --------------------------------------------------------------------------
# quote helpers
# --------------------------------------------------------------------------
def _ohlc_from(node: dict[str, Any]) -> Ohlc:
    z = Decimal("0")
    return Ohlc(
        open=_decimal(node.get("open")) or z,
        high=_decimal(node.get("high")) or z,
        low=_decimal(node.get("low")) or z,
        close=_decimal(node.get("close")) or z,
    )


# Angel always returns exactly 5 depth levels per side and ZERO-PADS the
# unused ones (live-verified 2026-07-21: post-close RELIANCE had one real bid
# and four {price: 0.0, quantity: 0} fillers, with the entire sell side
# padded; an ATM NIFTY call had the mirror image). Passing those through made
# `ask_price` come back as ₹0 — a price no strategy should ever see — so
# padding levels are dropped and bid/ask fall back to None when a side is
# genuinely empty.
def _levels(raw: Any) -> list[DepthLevel]:
    out: list[DepthLevel] = []
    for level in raw or []:
        price = _decimal(level.get("price"))
        if price is None or price <= 0:
            continue
        out.append(DepthLevel(price=price, quantity=_int(level.get("quantity"))))
    return out


# opnInterest is only meaningful on derivatives. Angel still returns a large
# non-zero value for CASH instruments (live: RELIANCE-EQ came back with
# opnInterest 268,716,500, while a real NIFTY option showed 45,467,305) —
# equities have no open interest, so whatever that number is, it isn't one.
# Surfacing it as `Quote.open_interest` would be actively misleading, so it's
# nulled outside the derivative segments.
_OI_EXCHANGES = {"NFO", "BFO", "MCX"}


def _node_to_quote(node: dict[str, Any]) -> Quote:
    """FULL-mode node -> Quote. Prices are rupee floats (REST is not in
    paise). Depth is a nested {buy: [{price, quantity, orders}], sell: [...]}."""
    depth = node.get("depth") or {}
    buy_depth = _levels(depth.get("buy"))
    sell_depth = _levels(depth.get("sell"))
    open_interest = (
        _float_or_none(node.get("opnInterest"))
        if node.get("exchange") in _OI_EXCHANGES
        else None
    )
    return Quote(
        last_price=_decimal(node.get("ltp")) or Decimal("0"),
        ohlc=_ohlc_from(node),
        volume=_int(node.get("tradeVolume")),
        day_change=_decimal(node.get("netChange")),
        day_change_perc=_float_or_none(node.get("percentChange")),
        bid_price=buy_depth[0].price if buy_depth else None,
        bid_quantity=buy_depth[0].quantity if buy_depth else None,
        ask_price=sell_depth[0].price if sell_depth else None,
        ask_quantity=sell_depth[0].quantity if sell_depth else None,
        buy_depth=buy_depth,
        sell_depth=sell_depth,
        upper_circuit=_decimal(node.get("upperCircuit")),
        lower_circuit=_decimal(node.get("lowerCircuit")),
        open_interest=open_interest,
        average_price=_decimal(node.get("avgPrice")),
        last_trade_time=_quote_dt(node.get("exchTradeTime")),
    )


def _quote_dt(value: Any) -> datetime | None:
    """FULL quote times are like "21-Jul-2026 15:59:56" (IST)."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
