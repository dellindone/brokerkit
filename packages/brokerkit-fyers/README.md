# brokerkit-fyers

BrokerKit's Fyers adapter — wraps the official `fyers-apiv3` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming).

Fyers is BrokerKit's primary **data** source (free market/historical/streaming data, unlike Groww which needs a paid subscription for the same) — `market`, `historical`, and `streaming` got the most scrutiny in this adapter — but the full `Broker` contract is implemented, no data-only shortcuts.

## Install

```bash
pip install brokerkit-core brokerkit-fyers
```

## Prerequisites (Fyers dashboard)

1. Create an API app at [myapi.fyers.in/dashboard](https://myapi.fyers.in/dashboard) — you get a `client_id` (App ID) and `secret_key` (App Secret), and register a `redirect_uri` (a plain `http://127.0.0.1:<port>/` URL).
2. Enable TOTP-based 2FA on your Fyers login and note the **TOTP secret** (same secret you'd scan into an authenticator app).
3. Know your **Fyers ID** (login username, e.g. `"FAJ46068"`) and your 4-digit trading **PIN**.
4. **One-time only, per app:** activate the app via a real browser login —

   ```python
   from brokerkit_fyers import get_access_token

   get_access_token(client_id="...", secret_key="...", redirect_uri="http://127.0.0.1:5000/")
   ```

   Opens a browser to log in, catches the redirect on a local server, and prints an `access_token` — that's just proof the app + credentials work end-to-end, you don't need to save it. Confirmed necessary by testing: a brand-new app returns `"invalid totp"` on step 4 below until this has been done once; it worked immediately after. Exact mechanism unconfirmed (Fyers doesn't document this), but the fix is repeatable.

After that one-time step, everything is credential-only — no more browser, no token to copy-paste.

## Auth, honestly

Fyers' *officially documented* auth is browser-redirect only: `generate-authcode` → you log in in a browser → Fyers redirects with an `auth_code` → `validate-authcode` exchanges it for an `access_token`. There's no SDK-wrapped way to skip that browser round-trip through the official flow alone — that's what `get_access_token()` above does, and per the testing above, a new app seems to need it run once regardless.

`FyersAuth` (used by `create_broker("fyers", ...)` for every login after that) instead drives the same internal endpoints Fyers' own web login uses (`api-t2.fyers.in/vagator/v2/*`) — TOTP for the OTP step, PIN for the next — to get an `auth_code` programmatically, then finishes with the *official*, documented exchange (`SessionModel.generate_token()`). This is a known community pattern, not something invented here; it was adopted after cross-verifying against a previously-working implementation of the same flow, not guessed. `login()` does this full sequence fresh every time — no persisted refresh_token to track, same ergonomics as `GrowwAuth`. `FyersBroker._auto_refresh_loop()` sleeps until the token's assumed expiry (Fyers gives no reliable expiry signal, unlike Groww's deterministic 6 AM IST) and re-logs in automatically. **Verified live 2026-07-20** against a real account (auth + instrument fetch + quote).

**Trade-off, stated plainly:** the `auth_code`-acquisition part of `FyersAuth` isn't part of any Fyers SDK or public API contract — it plays back a sequence the Fyers *website* uses internally, not a documented integration surface. It could break without notice on a UI/security change on Fyers' end. If that ever happens, only `brokerkit_fyers/auth.py` needs to change — the rest of the adapter is unaffected, and `get_access_token()` (the official flow) still works as a fallback.

### `get_access_token()` internals

Runs a tiny local Flask server on your `redirect_uri` to catch `auth_code` directly instead of asking you to copy-paste it from the browser address bar — manual copy-paste of that (very long) JWT is exactly what caused an `"invalid auth code"` failure while first building this. Can also be run from the command line: `python -m brokerkit_fyers.login_helper <client_id> <secret_key> <redirect_uri>`.

## Quick start

```python
import asyncio

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "fyers",
        client_id="XC4EOD67IM-100",
        secret_key="...",
        redirect_uri="http://127.0.0.1:5000/",
        fy_id="FAJ46068",
        totp_secret="...",
        pin="1234",
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

Verified live 2026-07-20 (no auth needed): `fetch_instruments()` against the real public CSVs (~128k instruments across EQ/IDX/FUT/CE/PE, `RELIANCE-EQ` resolves correctly with real ISIN/tick size). The TOTP+PIN login sequence itself was cross-verified against a previously-working implementation, not guessed. Orders, portfolio, market data, and streaming are code-complete and unit-checked against real captured response shapes, but not yet exercised against a live account.
