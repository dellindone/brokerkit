# brokerkit-fyers

BrokerKit's Fyers adapter — wraps the official `fyers-apiv3` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming).

Fyers is BrokerKit's primary **data** source (free market/historical/streaming data, unlike Groww which needs a paid subscription for the same) — `market`, `historical`, and `streaming` got the most scrutiny in this adapter — but the full `Broker` contract is implemented, no data-only shortcuts.

## Install

```bash
pip install brokerkit-core brokerkit-fyers
```

## Prerequisites (Fyers dashboard)

1. Create an API app at [myapi.fyers.in/dashboard](https://myapi.fyers.in/dashboard) — you get a `client_id` (App ID) and `secret_key` (App Secret), and register a `redirect_uri`.
2. Know your Fyers trading **PIN** (the 4-digit PIN used for order confirmation / token refresh).
3. Run `login_helper.py` (in this package) **once, manually** — it opens a browser for you to log in and prints an `access_token` + `refresh_token`. Save both.

## Why the manual step — Fyers auth, honestly

Unlike Groww (pure TOTP, fully silent), Fyers' *official* auth is browser-redirect only: `generate-authcode` → you log in in a browser → Fyers redirects with an `auth_code` → `validate-authcode` exchanges it for an `access_token` (valid ~24h) + `refresh_token` (valid ~15 days). There's no officially-documented, SDK-wrapped way to skip that first browser round-trip.

What FyersBroker *does* automate: once you have that initial pair, it self-refreshes the `access_token` in the background using the `refresh_token` + your PIN via Fyers' `/validate-refresh-token` endpoint — not wrapped by the SDK, so `brokerkit_fyers.auth.FyersAuth` calls it directly. This works for up to ~15 days without touching a browser again, on the same cadence idea as `GrowwBroker`'s auto-refresh loop (see `FyersBroker._auto_refresh_loop`). After ~15 days (or if the refresh_token is ever invalidated), you re-run `login_helper.py` once and restart the broker with the fresh pair.

(There's a widely-used *unofficial* trick — TOTP + PIN hitting Fyers' undocumented internal login endpoints — that gets fully silent login like Groww's. Deliberately not implemented here: it's reverse-engineered, not part of any SDK, and could break or draw ToS scrutiny without notice.)

## Quick start

```python
import asyncio

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "fyers",
        client_id="XC4EOD67IM-100",
        secret_key="...",
        pin="1234",
        access_token="...",   # from login_helper.py
        refresh_token="...",  # from login_helper.py
    )

    instruments = await broker.instruments.fetch_instruments()
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE-EQ" and i.exchange == Exchange.NSE and i.segment == Segment.CASH
    )

    quote = await broker.market.get_quote(reliance)
    print("LTP:", quote.last_price)

    await broker.close()


asyncio.run(main())
```

## What you get on `broker`

### `broker.instruments` — `InstrumentProvider`

```python
instruments = await broker.instruments.fetch_instruments()  # list[Instrument]
```

Fyers has no single combined instrument file like Groww — this downloads and normalizes five public per-exchange/segment CSVs (`NSE_CM`, `NSE_FO`, `BSE_CM`, `BSE_FO`, `MCX_COM`; no auth needed) concurrently and concatenates them (~128k instruments as of 2026-07-20). Currency derivatives (`NSE_CD`) are deliberately excluded — core's `Segment` enum has no `CURRENCY` value.

### `broker.market` — `MarketDataProvider`

```python
await broker.market.get_quote(reliance)             # Quote
await broker.market.get_ltp([reliance, tcs])         # dict[symbol, Decimal]
await broker.market.get_ohlc([reliance, tcs])        # dict[symbol, Ohlc]
```

`get_ltp`/`get_ohlc` batch up to 50 symbols per call (Fyers' own limit) and chunk automatically. Note: Fyers' `/quotes` doesn't return market depth or circuit limits (those live on a separate `/depth` endpoint this adapter doesn't call for `get_quote`) — the resulting `Quote` is narrower than Groww's equivalent on those fields; that's a real capability difference between the two brokers, not a bug here.

### `broker.historical` — `HistoricalDataProvider`

```python
from datetime import datetime, timedelta

candles = await broker.historical.get_candles(
    reliance, start=datetime.now() - timedelta(days=7), end=datetime.now(), interval_minutes=1440,
)
```

### `broker.streaming` — `StreamingProvider`

```python
async def on_tick(tick):
    print(tick.symbol, tick.ltp)

await broker.streaming.subscribe_ltp([reliance], on_tick)
await broker.streaming.unsubscribe_ltp([reliance])
await broker.streaming.close()
```

Two Fyers SDK quirks worth knowing (verified from `fyers_apiv3` source, not guessed):

- **`FyersDataSocket` is a process-wide singleton.** A second `FyersStreaming` in the same process (e.g. a second Fyers account via `BrokerManager`) would silently hijack the first one's connection — `FyersStreaming` detects this and raises `StreamingError` instead of letting that happen. Only one Fyers streaming connection per process for now.
- **Reconnects wipe the SDK's own subscription state.** `FyersStreaming` hooks the reconnect callback to automatically replay your tracked subscriptions, so a network blip doesn't silently kill the stream — but this hasn't been exercised against a real dropped connection yet.

`open_interest` on `Tick` is always `None` for Fyers — the SDK's own LTP feed explicitly strips that field before dispatching (confirmed in `FyersWebsocket/data_ws.py`), not an adapter gap.

### `broker.orders` — `OrderProvider`

```python
from decimal import Decimal
from brokerkit import OrderRequest, OrderType, Product, TransactionType

order = await broker.orders.place_order(OrderRequest(
    instrument=reliance, transaction_type=TransactionType.BUY, order_type=OrderType.LIMIT,
    quantity=1, product=Product.CNC, price=Decimal("2500"),
))
await broker.orders.modify(order.order_id, reliance.segment, price=Decimal("2510"))
await broker.orders.cancel(order.order_id, reliance.segment)
await broker.orders.get_order(order.order_id, reliance.segment)
await broker.orders.list_orders()
```

Fyers has no single-order lookup endpoint — `get_order`/`list_orders` fetch the whole orderbook and filter, same as the official SDK's own `get_orders()` helper does internally. No client-side pre-validation, same philosophy as the Groww adapter — Fyers rejects invalid orders and the reason comes back as `Order.status_message`.

### `broker.portfolio` — `PortfolioProvider`

```python
await broker.portfolio.holdings()   # list[Holding]
await broker.portfolio.positions()  # list[Position]
```

Fyers' holdings response carries no ISIN — `Holding.isin` is always `None` for this adapter.

## Errors

Fyers' SDK never raises on an API-level failure — every call just returns `{"s": "error", ...}`, even for auth problems. This adapter inspects that (`brokerkit_fyers/errors.py`) and translates it into the same core exceptions Groww uses, so your code never needs to know the difference:

```python
from brokerkit import BrokerKitError, OrderError

try:
    await broker.orders.place_order(request)
except OrderError as e:
    print("order failed:", e)
```

## Live verification status

Verified live 2026-07-20 (no auth needed): `fetch_instruments()` against the real public CSVs (~128k instruments across EQ/IDX/FUT/CE/PE, `RELIANCE-EQ` resolves correctly with real ISIN/tick size). Auth, orders, portfolio, market data, and streaming are code-complete and unit-checked against real captured response shapes, but not yet exercised against a live account — that needs a real `client_id`/`secret_key`/PIN to run `login_helper.py` against.
