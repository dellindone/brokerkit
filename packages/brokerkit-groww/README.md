# brokerkit-groww

BrokerKit's Groww adapter — wraps the official `growwapi` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming).

You write strategy code against `brokerkit-core`'s types; this package is what makes `"groww"` work with `create_broker(...)`.

## Install

```bash
pip install brokerkit-core brokerkit-groww
```

## Prerequisites (Groww dashboard)

1. **TOTP credentials** — Groww's API auth is TOTP-only. Get your `api_key` + `totp_secret` from the Groww API dashboard.
2. **Static IP registration** ("Add static IP" on the dashboard) — required by SEBI rules for order placement. Without it, `orders.place_order()` fails with an IP-rejection error (reads — holdings, instruments — still work fine).
3. **Trading API subscription** (₹499/month + taxes) — required for market data (quotes, LTP, OHLC, historical candles) and streaming. Without it, those calls raise `BrokerKitError("Access forbidden...")`.

Auth, instrument lookup, and portfolio reads work without either of the above.

## Quick start

```python
import asyncio
import os

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "groww",
        totp_key=os.environ["GROWW_API_KEY"],
        totp_secret=os.environ["GROWW_TOTP_SECRET"],
    )

    instruments = await broker.instruments.fetch_instruments()
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE" and i.exchange == Exchange.NSE and i.segment == Segment.CASH
    )

    quote = await broker.market.get_quote(reliance)
    print("LTP:", quote.last_price)

    holdings = await broker.portfolio.holdings()
    print("Holdings:", holdings)

    await broker.close()


asyncio.run(main())
```

Using `create_broker("groww", ...)` (rather than importing `GrowwBroker` directly) keeps your strategy code broker-agnostic — swapping to another broker later is a one-line change. Direct import (`from brokerkit_groww import GrowwBroker; await GrowwBroker.create(...)`) works identically if you don't need that.

A fuller runnable version lives in [`examples/basic/main.py`](../../examples/basic/main.py).

## What you get on `broker`

Every provider below is an instance of the corresponding ABC from `brokerkit-core` (`brokerkit.interfaces`), so the same calls work against any future broker adapter.

### `broker.instruments` — `InstrumentProvider`

```python
instruments = await broker.instruments.fetch_instruments()  # list[Instrument]
```
Downloads and normalizes Groww's full instrument master (~145k rows) on every call — no caching in the framework. Filter/search app-side.

### `broker.orders` — `OrderProvider`

```python
from decimal import Decimal
from brokerkit import OrderRequest, OrderType, Product, TransactionType

order = await broker.orders.place_order(OrderRequest(
    instrument=reliance,
    transaction_type=TransactionType.BUY,
    order_type=OrderType.LIMIT,
    quantity=1,
    product=Product.CNC,
    price=Decimal("2500"),
))

await broker.orders.modify(order.order_id, reliance.segment, price=Decimal("2510"))
await broker.orders.cancel(order.order_id, reliance.segment)
await broker.orders.get_order(order.order_id, reliance.segment)
await broker.orders.list_orders()
```
No client-side pre-validation (freeze qty, buy/sell allowed, etc.) — Groww rejects invalid orders and the rejection reason comes back as `Order.status_message`.

### `broker.portfolio` — `PortfolioProvider`

```python
await broker.portfolio.holdings()   # list[Holding] — demat-level, ISIN-identified
await broker.portfolio.positions()  # list[Position] — per trade, today's book
```

### `broker.market` — `MarketDataProvider`

```python
await broker.market.get_quote(reliance)                 # Quote — LTP, OHLC, depth, circuits
await broker.market.get_ltp([reliance, infy, tcs])       # dict[symbol, Decimal]
await broker.market.get_ohlc([reliance, infy])           # dict[symbol, Ohlc]
```
`get_ltp`/`get_ohlc` batch and chunk internally (Groww allows up to 50 symbols per call, one segment at a time) — pass as many instruments as you want.

### `broker.historical` — `HistoricalDataProvider`

```python
from datetime import datetime, timedelta

candles = await broker.historical.get_candles(
    reliance,
    start=datetime.now() - timedelta(days=7),
    end=datetime.now(),
    interval_minutes=1440,  # daily
)
```

### `broker.streaming` — `StreamingProvider`

```python
async def on_tick(tick):
    print(tick.symbol, tick.ltp)

await broker.streaming.subscribe_ltp([reliance], on_tick)
# ... later
await broker.streaming.unsubscribe_ltp([reliance])
await broker.streaming.close()
```
Callback can be sync or async. Requires `instrument.exchange_token` to be set (comes from `fetch_instruments()`).

## Auth & token lifetime

Groww's TOTP flow has three layers, easy to mix up:

- **TOTP secret** (`totp_secret`) — never expires. Used to generate a fresh 6-digit code every 30 seconds.
- **TOTP code** — lives 30 seconds, but only matters at login; it's consumed once to fetch the access token and then discarded.
- **Access token** — the thing that actually authenticates every API call. Expires daily at **6 AM IST**.

You don't need to think about any of this during normal use: `GrowwBroker` runs a background refresh loop (started in `create()`, stopped in `close()`) that sleeps until the token's known 6 AM IST expiry, re-logs in, and swaps the token in place — every provider (`orders`, `portfolio`, `market`, ...) picks it up automatically since they all share one underlying client. A long-running bot survives across days without manual re-auth. If a refresh attempt fails (network blip), it retries after 60s rather than dying silently.

## Errors

Every `growwapi` exception is translated into a `brokerkit` exception before it reaches your code — you never need to catch `growwapi.groww.exceptions.*` directly:

```python
from brokerkit import BrokerKitError, OrderError, StreamingError

try:
    await broker.orders.place_order(request)
except OrderError as e:
    print("order failed:", e)
```

## Multiple accounts

Each `GrowwBroker` instance owns its own client and providers, so multiple accounts (Groww or mixed with future brokers) run independently via `BrokerManager`:

```python
from brokerkit import BrokerManager

manager = BrokerManager()
await manager.add("primary", "groww", totp_key=k1, totp_secret=s1)
await manager.add("secondary", "groww", totp_key=k2, totp_secret=s2)

await manager["primary"].orders.place_order(request)
await manager.close_all()
```
