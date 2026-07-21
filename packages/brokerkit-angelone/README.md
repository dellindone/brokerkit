# brokerkit-angelone

BrokerKit's Angel One adapter — wraps the official `smartapi-python` SDK behind BrokerKit's broker-agnostic interfaces (auth, instruments, orders, portfolio, market data, historical candles, streaming), plus two Angel-only extras: **charges** and **analytics**.

```bash
pip install brokerkit-core brokerkit-angelone
```

Angel One is a live-execution account **and** a second free data source: unlike Groww, Dhan and Zerodha, its market and historical data need no paid subscription. That makes it, alongside Fyers, one of the two brokers here where the data side works out of the box.

## Prerequisites

1. Create an app at [smartapi.angelone.in](https://smartapi.angelone.in) → you get the `api_key`.
2. Enable **TOTP** on the Angel account (Profile → Settings → TOTP) and note the secret.
3. Your `client_code` (e.g. `A123456`) and your **MPIN** — API login uses the MPIN, not the web password.
4. **Static IP registration** for order placement (SEBI rule). Reads work without it. Angel has **no sandbox**, so there is no way around this for writes.

## Quick start

```python
import asyncio
import os

from brokerkit import Exchange, Segment, create_broker


async def main():
    broker = await create_broker(
        "angelone",
        api_key=os.environ["ANGEL_API_KEY"],
        client_code=os.environ["ANGEL_CLIENT_CODE"],
        mpin=os.environ["ANGEL_MPIN"],
        totp_secret=os.environ["ANGEL_TOTP_SECRET"],
    )

    instruments = await broker.instruments.fetch_instruments()
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE-EQ"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )

    quote = await broker.market.get_quote(reliance)
    print(quote.last_price, quote.volume)

    await broker.close()


asyncio.run(main())
```

All four credentials are required — there is deliberately **no token passthrough** here (see below).

## The auth quirk worth understanding

Angel is the only broker in BrokerKit with a **real refresh-token endpoint** (`generateToken(refreshToken)`), so the daily refresh needs no TOTP re-entry. There is a reason it ships one:

**Angel's JWT expires on a wall-clock boundary, not after a fixed duration.** Two tokens minted at different times both carried an identical expiry of 00:00:00 IST — meaning a morning login lasts most of a day and an 11:30 PM login lasts half an hour. The adapter therefore decodes the token's own `exp` claim rather than assuming any validity window; an assumed 24 hours made dead tokens look fresh and every call failed `AG8001`.

The feed token from the same login response is a genuine rolling 24 hours — the two tokens have different expiry semantics.

This is also why there is **no `access_token` passthrough** in this adapter, unlike Fyers/Upstox/Dhan. Those earn theirs (Dhan rate-limits token generation, Upstox needs a daily browser login). Angel's login is headless and takes about a second, and its JWT dies quickly, so a pasted token is stale almost immediately — it was a pure footgun.

## Extras

### `broker.charges`

Implements the core `ChargesProvider` via Angel's `estimateCharges`.

```python
from decimal import Decimal
from brokerkit.enums import Product, TransactionType

charges = await broker.charges.get_brokerage(
    reliance, quantity=10, product=Product.CNC,
    transaction_type=TransactionType.BUY, price=Decimal("1400"),
)
```

### `broker.analytics`

Angel-specific market analytics, kept adapter-local (deliberately *not* forced into Upstox's `MarketInformationProvider`, whose twelve methods don't map onto these):

```python
await broker.analytics.put_call_ratio()
await broker.analytics.gainers_losers(datatype="PercPriceGainers", expirytype="NEAR")
await broker.analytics.option_greek(name="NIFTY", expiry=expiry)
await broker.analytics.oi_buildup(expirytype="NEAR", datatype="Long Built Up")
await broker.analytics.nse_intraday()
await broker.analytics.bse_intraday()
```

These return Angel's raw `data` payload rather than typed models — their shapes are auth-gated and not yet live-verified, and typing them from docs alone would risk silently wrong parsing.

## Adapter notes

- **Both `strike` and `tick_size` in the master are in paise** — the adapter divides by 100. Verified against real rows (a NIFTY 30000-PE carries `strike="3000000"`).
- **The master has no ISIN column**, so `Instrument.isin` is always `None`. ISIN does appear per-holding on the portfolio response. For cross-broker joins use `exchange_token` — it matches Fyers, Dhan, Groww and Zerodha exactly.
- **No server-side option-chain endpoint.** `get_option_chain` is assembled: filter the master for the underlying's contracts at that expiry, trim to the nearest strikes around spot, quote them, then best-effort merge greeks from the separate `optionGreek` endpoint — degrading to `greeks=None` rather than failing the whole chain. `expiry_list(underlying)` is provided as an adapter extra.
- **`variety` is a separate axis from order type.** Stop-loss orders go as variety `STOPLOSS`, everything else `NORMAL`, and both modify and cancel need the original variety — so both pre-fetch the order-book entry.
- **Depth is zero-padded to 5 levels** by Angel; the adapter drops padding rows rather than reporting an ask of ₹0. Equity `opnInterest` is junk, so `Quote.open_interest` is nulled outside F&O and commodities.
- **`Tick.minute_ohlc` is always `None`** — Angel's feed has no server-computed minute candle. Aggregate ticks yourself.
- **The SDK doesn't declare its own dependencies** (`logzero`, `websocket-client`), so this package declares them; it also makes a blocking network call at import time and writes a `logs/` directory into the working directory. Both are unavoidable SDK side effects, documented rather than worked around.

## Verification status

Live-verified against a real account: auth, instruments, LTP/OHLC/full quote, historical at daily/15m/1m, expiry list, the whole assembled option-chain path, portfolio, and order list. Angel's free data means none of the Groww/Dhan/Zerodha subscription walls apply.

Not yet verified live: streaming, the analytics extras, charges through the provider, and all order writes (SEBI static IP, with no Angel sandbox to sidestep it).

## License

MIT © 2026 Aditya Vishwakarma
