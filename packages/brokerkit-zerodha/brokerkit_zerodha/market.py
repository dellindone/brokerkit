import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import InstrumentType
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.market import MarketDataProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.option_chain import (
    OptionChain,
    OptionChainStrike,
    OptionContract,
)
from brokerkit.models.quote import Ohlc, Quote

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors
from brokerkit_zerodha.instruments import fetch_master_rows

# Kite's documented per-call cap for the market-quote endpoints. The full
# /quote endpoint is the strictest of the three, so one conservative chunk
# size is used everywhere rather than three different ones.
_MAX_PER_CALL = 500


class ZerodhaMarketData(MarketDataProvider):
    """Market data via Kite's /quote, /quote/ohlc and /quote/ltp endpoints.

    **Requires the paid ₹500/mo Kite Connect plan.** The free Personal plan
    covers orders/portfolio only — no live market data and no historical
    candles. That is an account-state wall, not an adapter bug (same posture
    as Groww's and Dhan's paid Data API subscriptions), and it is the
    opposite way round from Fyers/Angel, whose data is free while execution
    is what costs.
    """

    def __init__(self, client):
        self._client = client  # shared KiteConnect
        self._master_cache: tuple[date, list[dict[str, str]]] | None = None

    # ---------------------------------------------------------------- quotes
    async def get_quote(self, instrument: Instrument) -> Quote:
        key = mapper.quote_key(instrument)
        with zerodha_errors():
            raw = await asyncio.to_thread(self._client.quote, [key])
        entry = (raw or {}).get(key)
        if entry is None:
            raise BrokerKitError(f"No quote returned for {key}")
        return mapper.kite_to_quote(entry, instrument)

    async def get_ltp(self, instruments: list[Instrument]) -> dict[str, Decimal]:
        raw = await self._batched(self._client.ltp, instruments)
        out: dict[str, Decimal] = {}
        for inst in instruments:
            entry = raw.get(mapper.quote_key(inst))
            if entry is None:
                continue
            price = mapper._decimal(entry.get("last_price"))
            if price is not None:
                out[inst.symbol] = price
        return out

    async def get_ohlc(self, instruments: list[Instrument]) -> dict[str, Ohlc]:
        raw = await self._batched(self._client.ohlc, instruments)
        out: dict[str, Ohlc] = {}
        for inst in instruments:
            entry = raw.get(mapper.quote_key(inst))
            if entry is None:
                continue
            out[inst.symbol] = mapper.kite_to_ohlc(entry.get("ohlc"))
        return out

    async def _batched(self, method, instruments: list[Instrument]) -> dict[str, Any]:
        """Chunk into <=500 keys per call and merge. Responses come back
        keyed by the same "EXCHANGE:TRADINGSYMBOL" string that was sent, so
        merging is a plain dict update — no re-keying needed (unlike Upstox,
        whose LTP response keys differ from its request keys)."""
        keys = [mapper.quote_key(i) for i in instruments]
        merged: dict[str, Any] = {}
        for start in range(0, len(keys), _MAX_PER_CALL):
            chunk = keys[start : start + _MAX_PER_CALL]
            with zerodha_errors():
                part = await asyncio.to_thread(method, chunk)
            merged.update(part or {})
        return merged

    # ---------------------------------------------------------- option chain
    async def expiry_list(self, underlying: Instrument) -> list[date]:
        """Every expiry Kite lists for this underlying's options, ascending.
        An adapter extra (not on the shared ABC) — same precedent as the
        Dhan and Angel adapters, and needed because `get_option_chain`
        demands an exact expiry."""
        rows = await self._master()
        name = (underlying.name or underlying.symbol).upper()
        found = set()
        for row in rows:
            if row.get("instrument_type") not in ("CE", "PE"):
                continue
            if (row.get("name") or "").upper() != name:
                continue
            expiry = mapper._master_expiry(row.get("expiry", ""))
            if expiry is not None:
                found.add(expiry)
        return sorted(found)

    async def get_option_chain(
        self, underlying: Instrument, expiry: date, strike_count: int = 10
    ) -> OptionChain:
        """**Kite has no server-side option-chain endpoint** (verified against
        the SDK's full route table — there is no chain route at all), so the
        chain is assembled here, the same way the Angel adapter does it:
        filter the master for this underlying's CE/PE contracts at `expiry`,
        trim to the `strike_count` nearest strikes around spot, then quote
        them in one batched call.

        **Kite also has no greeks endpoint anywhere**, so `greeks` is always
        None for this adapter — a real capability gap, not a mapping bug.
        Angel at least has a separate `optionGreek` call to merge in; Kite
        has nothing to merge. Use the Fyers or Upstox adapter if greeks are
        needed.
        """
        rows = await self._master()
        name = (underlying.name or underlying.symbol).upper()

        contracts: list[Instrument] = []
        for row in rows:
            if row.get("instrument_type") not in ("CE", "PE"):
                continue
            if (row.get("name") or "").upper() != name:
                continue
            if mapper._master_expiry(row.get("expiry", "")) != expiry:
                continue
            try:
                inst = mapper.parse_master_row(row)
            except (ValueError, KeyError):
                continue
            if inst is not None and inst.strike is not None:
                contracts.append(inst)

        if not contracts:
            raise BrokerKitError(
                f"No {name} option contracts found for expiry {expiry} in Kite's master"
            )

        spot = await self._spot(underlying)
        strikes = sorted({c.strike for c in contracts if c.strike is not None})
        keep = set(sorted(strikes, key=lambda s: abs(s - spot))[:strike_count])
        contracts = [c for c in contracts if c.strike in keep]

        quotes = await self._batched(self._client.quote, contracts)

        by_strike: dict[Decimal, dict[str, OptionContract]] = {}
        for inst in contracts:
            entry = quotes.get(mapper.quote_key(inst))
            if entry is None:
                continue
            depth = entry.get("depth") or {}
            buy = mapper._depth(depth.get("buy"))
            sell = mapper._depth(depth.get("sell"))
            contract = OptionContract(
                symbol=inst.symbol,
                strike=inst.strike,  # type: ignore[arg-type]
                option_type=inst.instrument_type,
                ltp=mapper._decimal(entry.get("last_price")) or Decimal("0"),
                open_interest=mapper._int(entry.get("oi")),
                volume=mapper._int(entry.get("volume") or entry.get("volume_traded")),
                bid_price=buy[0].price if buy else None,
                ask_price=sell[0].price if sell else None,
                greeks=None,  # Kite has no greeks endpoint at all
            )
            slot = by_strike.setdefault(inst.strike, {})  # type: ignore[arg-type]
            slot["call" if inst.instrument_type is InstrumentType.CE else "put"] = contract

        return OptionChain(
            underlying_symbol=underlying.symbol,
            underlying_ltp=spot,
            expiry=expiry,
            strikes=[
                OptionChainStrike(
                    strike=strike,
                    call=by_strike[strike].get("call"),
                    put=by_strike[strike].get("put"),
                )
                for strike in sorted(by_strike)
            ],
        )

    async def _spot(self, underlying: Instrument) -> Decimal:
        ltp = await self.get_ltp([underlying])
        price = ltp.get(underlying.symbol)
        if price is None:
            raise BrokerKitError(f"Could not fetch spot price for {underlying.symbol}")
        return price

    async def _master(self) -> list[dict[str, str]]:
        """Kite's master is ~10 MB; cache it for the calendar day so a chain
        call doesn't re-download it every time (same approach as the Angel
        adapter, which caches a 35 MB master)."""
        today = datetime.now().date()
        if self._master_cache is not None and self._master_cache[0] == today:
            return self._master_cache[1]
        rows = await fetch_master_rows()
        self._master_cache = (today, rows)
        return rows
