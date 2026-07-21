# brokerkit-dhan

BrokerKit's Dhan adapter — wraps the official `dhanhq` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming), plus three Dhan-only extras: **US equities**, **risk control** and a **sandbox**.

```bash
pip install brokerkit-core brokerkit-dhan
```

This is the broadest-scope adapter in BrokerKit. Dhan is a second live-execution account, the only source of **Global Stocks** (US equity trading — no other broker here has it), and the source of real risk tooling.

## Prerequisites

1. **Enable TOTP** on the account first — web.dhan.co → DhanHQ APIs → Setup TOTP. Without it, token generation fails.
2. Your `client_id` and login `pin`.
3. **Static IP registration** for order placement (SEBI rule). Reads work without it.
4. **Data API subscription** — required for market data, historical candles, option chain and streaming. Without it those calls fail on subscription (historical returns a clean `DH-902`), same posture as Groww.
5. **US account activation**, only if you want Global Stocks holdings/funds. Instruments and market status work without it.

## Quick start

```python
import asyncio
import os

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "dhan",
        client_id=os.environ["DHAN_CLIENT_ID"],
        pin=os.environ["DHAN_PIN"],
        totp_secret=os.environ["DHAN_TOTP_SECRET"],
        # Strongly recommended — see below
        access_token=os.environ.get("DHAN_ACCESS_TOKEN"),
    )

    instruments = await broker.instruments.fetch_instruments()
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )

    print(await broker.portfolio.holdings())
    await broker.close()


asyncio.run(main())
```

**Use the `access_token` passthrough.** Dhan rate-limits token generation to **once every 2 minutes**, so re-running a script repeatedly will hit `"Token can be generated once every 2 minutes."` Generate once, reuse it; `pin` + `totp_secret` are still used for the 24-hour refresh.

## Extras

### `broker.global_stocks` — US equities

Core models genuinely cannot represent this — core `OrderRequest.quantity` is an `int` but Global Stocks supports fractional shares, core `Exchange` has no US value, and prices are USD — so this has its own adapter-local models (`GlobalInstrument`, `GlobalOrder`, `GlobalHolding`, `GlobalFundLimit`, `GlobalMarketStatus`).

```python
us = await broker.global_stocks.fetch_instruments()      # ~11,458 US instruments
aapl = next(i for i in us if i.symbol == "AAPL")
print(aapl.security_id, aapl.exchange, aapl.fractional)

print(await broker.global_stocks.market_status())
```

Holdings and fund limits need US onboarding on the account (`INX-1007` otherwise); instruments and market status do not.

### `broker.risk_control` — kill switch + P&L auto-exit

```python
await broker.risk_control.kill_switch_status()
await broker.risk_control.activate_kill_switch()
await broker.risk_control.get_pnl_exit()
```

Dhan's kill switch is **account-wide** (Upstox's is per-segment).

### `broker.sandbox_orders` — order writes without the static-IP wall

Pass `sandbox_access_token=` (from developer.dhanhq.co) and `broker.sandbox_orders` gets wired. Dhan's sandbox covers a much broader surface than Upstox's — full order CRUD *and* reads.

It is deliberately a **separate attribute** from `broker.orders`, never merged, so a real order can never be confused with a sandbox one.

## Adapter notes

- **`tick_size` in the instrument master is in paise** — the adapter divides by 100. Verified against real rows: a ₹1400 stock cannot have a ₹10 tick.
- **Both instrument CSVs are needed.** The detailed CSV has ISIN and underlying but no trading symbol; the compact one has the symbol but neither of those. The adapter fetches both concurrently and joins them (195,524 instruments).
- **Empty holdings arrive as a failure envelope**, not `[]`. Dhan returns `DH-1111 "No holdings available"` as an error; the adapter translates it to an empty list.
- **Streaming uses Quote mode (17), not Ticker (15)**, specifically so `Tick.volume` populates — Ticker mode carries no volume.
- **`Tick.minute_ohlc` is always `None`** — Dhan's feed carries day OHLC only, no server-computed minute candle. Aggregate ticks yourself.
- **Uses `dhanhq==2.3.0rc1`, a pre-release, deliberately.** It is the only version with Global Stocks at all, and diffing it against stable 2.2.0 from source showed it is purely additive — no changed or removed signatures.

## Verification status

Live-verified: auth, instruments, portfolio, order list, Global Stocks instruments and market status, risk-control reads.

Blocked by account state rather than by code: market / historical / option chain / streaming need the paid Data API subscription (so their response parsing is written from docs and not yet live-confirmed); Global Stocks holdings and funds need US activation; real order writes need SEBI static IP or a sandbox token.

## License

MIT © 2026 Aditya Vishwakarma
