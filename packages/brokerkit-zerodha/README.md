# brokerkit-zerodha

BrokerKit's Zerodha adapter — wraps the official `kiteconnect` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming), plus two Zerodha-only extras: **charges** and **GTT**.

```bash
pip install brokerkit-core brokerkit-zerodha
```

## Read this first: two things Zerodha does differently

**1. There is no programmatic login. At all.** Kite Connect has no TOTP, no password grant, nothing headless — verified against the SDK source (zero TOTP/2FA references anywhere in `kiteconnect`) and the official docs, which describe only the browser flow. You open Zerodha's login page, log in there, and the redirect carries a `request_token` you exchange for an `access_token`. That token **expires at 6:00 AM IST the next day**, so this is a once-a-day step.

`renew_access_token` exists in the SDK, but Zerodha only issues the `refresh_token` it needs to "certain approved platforms" — a personal app generally never receives one, so there is no unattended refresh.

**2. The free plan has no market data.** This is the inverse of Groww and Dhan:

| Plan | Price | Includes |
|---|---|---|
| Personal | **free** | orders, GTT, portfolio, margins — **no live data, no historical** |
| Connect | ₹500/month | everything above **plus** WebSocket streaming and historical candles |

So on a free app, `market`, `historical` and `streaming` fail with a permission error. That is your subscription, not a bug — the adapter's error message says so explicitly.

There is also **no sandbox** of any kind (unlike Upstox and Dhan), so order writes additionally need SEBI static-IP registration with no way around it.

## Prerequisites

1. Create an app at [developers.kite.trade](https://developers.kite.trade) — you get an `api_key` and `api_secret`, and you register a redirect URL (use a plain `http://127.0.0.1:<port>/`).
2. **Static IP registration** for order placement (SEBI rule). Reads work without it.
3. The ₹500/mo Connect plan, only if you need market data / historical / streaming.

## Quick start

Mint a token once a day:

```bash
python -m brokerkit_zerodha.login_helper <api_key> <api_secret> http://127.0.0.1:5001/
```

This opens the browser and captures the redirect with a local server — nothing to copy-paste. (Port 5001, not 5000: macOS AirPlay Receiver squats on 5000 by default.)

Then reuse the printed token all day:

```python
import asyncio
import os

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "zerodha",
        api_key=os.environ["ZERODHA_API_KEY"],
        api_secret=os.environ["ZERODHA_API_SECRET"],
        access_token=os.environ["ZERODHA_ACCESS_TOKEN"],
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

Omit `access_token` and pass `redirect_uri=` instead, and `create()` will run the browser login itself — right for an interactive first run, wrong for anything unattended.

## Extras

### `broker.charges` — pre-trade cost estimate

Implements the core `ChargesProvider` via Kite's virtual contract note.

```python
from decimal import Decimal
from brokerkit.enums import Product, TransactionType

charges = await broker.charges.get_brokerage(
    reliance, quantity=10, product=Product.CNC,
    transaction_type=TransactionType.BUY, price=Decimal("1400"),
)
print(charges.total, charges.taxes.stt, charges.other_charges.sebi_turnover)
```

Works on the free plan.

### `broker.gtt` — Good-Till-Triggered orders

A standing instruction that sits on Zerodha's servers (up to a year) and fires a real order when price crosses a trigger. **No other broker in BrokerKit has this**, so it is adapter-local with its own models rather than forced into `OrderProvider` — GTTs are a separate order book with their own endpoints and lifecycle, not an order type.

```python
from decimal import Decimal
from brokerkit.enums import TransactionType
from brokerkit_zerodha import GttLeg

await broker.gtt.place(
    reliance,
    trigger_values=[Decimal("1500")],
    last_price=Decimal("1400"),          # current LTP; Kite validates against it
    legs=[GttLeg(transaction_type=TransactionType.SELL,
                 quantity=1, price=Decimal("1500"))],
)

for t in await broker.gtt.list_triggers():
    print(t.trigger_id, t.trading_symbol, t.status, t.trigger_values)
```

Two-leg (OCO — stop-loss and target together, whichever fires cancels the other) is supported with `trigger_type="two-leg"`, two ascending trigger values and two legs.

## Adapter notes

- **Instrument master is already in rupees.** Unlike Dhan, Angel One and Upstox, no paise division is needed — `tick_size` and `strike` come through as-is. The master is a public CSV needing no auth (122,526 rows → 82,715 normalized instruments).
- **Index rows carry `instrument_type` "EQ".** Kite's master has only four type values (EQ/FUT/CE/PE) and no index type; indices are identifiable only by `segment == "INDICES"`. Trusting `instrument_type` alone would classify all 220 indices as tradeable equities. The adapter maps them to `InstrumentType.IDX` correctly.
- **No option-chain endpoint and no greeks endpoint.** `get_option_chain` is assembled from the master plus batched quotes. `OptionContract.greeks` is **always `None`** here — Kite has nothing to merge. Use the Fyers or Upstox adapter if you need greeks.
- **`Instrument.isin` is always `None`** — Kite's master has no ISIN column. Join against other brokers on `exchange_token` (RELIANCE is `2885` on Groww, Fyers, Dhan and Zerodha alike).
- **Streaming runs on the Twisted global reactor.** `KiteTicker.stop()` calls `reactor.stop()`, which is process-wide and irreversible, so this adapter's `close()` deliberately closes only the socket. "full" mode is used rather than "quote" because the quote packet carries no timestamp field at all.
- **`Tick.minute_ohlc` is always `None`** — Kite's feed has no server-computed minute candle. Aggregate ticks yourself.

## Verification status

Live-verified against a real account: auth, instruments, portfolio, orders (read), and charges end to end.

Blocked by account state rather than by code: market / historical / streaming / option chain need the paid Connect plan; order and GTT writes need SEBI static IP, with no sandbox available to sidestep it.

## License

MIT © 2026 Aditya Vishwakarma
