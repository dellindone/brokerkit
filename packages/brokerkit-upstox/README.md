# brokerkit-upstox

BrokerKit's Upstox adapter — wraps the official `upstox-python-sdk` behind BrokerKit's broker-agnostic interfaces.

Upstox is BrokerKit's **fundamentals + news** source (structured financial data and market news, neither of which Groww or Fyers expose) — `fundamentals` and `news` got the most scrutiny in this adapter — but the full `Broker` contract is implemented, no data-only shortcuts.

## Install

```bash
pip install brokerkit-core brokerkit-upstox
```

## Two separate credentials — read this first

Unlike Groww/Fyers (one credential set for everything), Upstox genuinely needs up to two:

1. **Analytics Token** — generate once from your app's page on [account.upstox.com/developer/apps](https://account.upstox.com/developer/apps) (Analytics tab → Generate Token). 1-year validity, read-only, no static IP needed. Powers `instruments`, `historical`, `market`, `fundamentals`, `news` — the entire data side, with **zero daily login**.
2. **OAuth app credentials** (`client_id`/`client_secret`/`redirect_uri`, from the same Apps page) — the official browser-based authorization-code flow. Powers `orders`/`portfolio` only (Analytics Token is read-only and can't place orders). There is **no headless refresh** for this token — Upstox has no documented programmatic login, unlike Groww's TOTP or Fyers' TOTP+PIN. Every login (including the daily refresh once the token expires ~3:30 AM IST) opens a real browser; something needs to be watching it.

Give either or both to `create_broker`. Giving only the Analytics Token is the expected shape for this adapter's actual purpose — `orders`/`portfolio` simply aren't wired in that case, and accessing them raises `AttributeError` rather than failing silently.

```python
import asyncio
from brokerkit import Exchange, Segment, create_broker

async def main():
    # data-only (the common case)
    broker = await create_broker("upstox", analytics_token="...")

    # full contract, incl. orders/portfolio (opens a browser on first use)
    broker = await create_broker(
        "upstox",
        analytics_token="...",
        client_id="...", client_secret="...", redirect_uri="http://127.0.0.1:5000/",
    )

    instruments = await broker.instruments.fetch_instruments()
    reliance = next(i for i in instruments if i.symbol == "RELIANCE" and i.exchange == Exchange.NSE and i.segment == Segment.CASH)

    profile = await broker.fundamentals.get_company_profile(reliance)
    print(profile.sector, profile.sector_market_cap_inr.formatted)

    await broker.close()

asyncio.run(main())
```

## What you get on `broker`

### `broker.instruments` — `InstrumentProvider`

Public gzipped JSON per exchange (`NSE`/`BSE`/`MCX`, no auth needed) — normalizes to core `Instrument`, ~113k rows as of 2026-07-20. Every row's Upstox `instrument_key` (e.g. `"NSE_EQ|INE002A01018"`) is stashed in `Instrument.exchange_token` — every other provider in this package reads it back from there rather than reconstructing it.

### `broker.fundamentals` — `FundamentalsProvider` (new core interface)

```python
await broker.fundamentals.get_company_profile(reliance)      # CompanyProfile
await broker.fundamentals.get_balance_sheet(reliance)         # BalanceSheet
await broker.fundamentals.get_cash_flow(reliance)             # CashFlow
await broker.fundamentals.get_income_statement(reliance)      # IncomeStatement
await broker.fundamentals.get_share_holdings(reliance)        # list[FinancialLineItem]
await broker.fundamentals.get_key_ratios(reliance)             # list[KeyRatio]
await broker.fundamentals.get_corporate_actions(reliance)      # list[CorporateAction]
await broker.fundamentals.get_competitors(reliance)            # list[Competitor]
```

All 8 endpoints, looked up by `instrument.isin` (raises clearly if the `Instrument` has none) — except `get_competitors`, which Upstox itself keys by `instrument_key` instead of `isin` (a real API inconsistency, verified from the SDK source, not a typo here). `balance_sheet`/`cash_flow`/`income_statement` take an optional `statement_type` (`StatementType.CONSOLIDATED`/`STANDALONE`) and `include_full_statement` (line-item breakdown, off by default).

Not part of the shared `Broker` base class — a deliberate call (see ROADMAP Phase 10.8): only Upstox has this capability today, so Groww/Fyers aren't given an attribute they'll never implement.

### `broker.news` — `NewsProvider` (new core interface)

```python
await broker.news.get_news([reliance, tcs])   # list[NewsArticle] — up to 30 instruments/call
await broker.news.get_news_for_positions()    # your current open positions, resolved server-side
await broker.news.get_news_for_holdings()     # your holdings portfolio, resolved server-side
```

Articles from roughly the last 7 days only (Upstox's own retention window). The `positions`/`holdings` modes need no instrument list — Upstox resolves them against your account directly.

### `broker.market` — `MarketDataProvider`

```python
await broker.market.get_quote(reliance)        # Quote
await broker.market.get_ltp([reliance, tcs])   # dict[symbol, Decimal]
await broker.market.get_ohlc([reliance, tcs])  # dict[symbol, Ohlc]
```

Batches up to 500 instrument keys per call (well above Groww/Fyers' 50). Upstox splits LTP and OHLC into two separate endpoints (no combined "full quote" call) — `get_quote()` calls both and combines them.

```python
from datetime import date
chain = await broker.market.get_option_chain(nifty_index, expiry=date(2026, 7, 31), strike_count=10)
```

Upstox's option-chain response already groups by strike server-side (unlike Fyers' flat array needing client-side grouping). No `rho` in the greeks (same gap as Fyers). `underlying_ltp` isn't in this response at all — stays `0`; call `get_quote()` on the underlying separately if you need it.

### `broker.market_information` — `MarketInformationProvider` (new core interface)

Upstox's "Market Information" category — institutional-grade F&O analytics and market screeners with no Groww/Fyers equivalent, so (like `fundamentals`/`news`) this is a `UpstoxBroker`-only extra, not on the shared `Broker` base.

```python
from datetime import date

await broker.market_information.get_oi(nifty_index, expiry="2026-05-29", for_date=date(2026, 5, 20))
await broker.market_information.get_change_in_oi(nifty_index, expiry="current_week", for_date=date.today(), lookback_days=1)
await broker.market_information.get_max_pain(nifty_index, expiry="current_week", for_date=date.today(), bucket_interval_minutes=60)
await broker.market_information.get_pcr(nifty_index, expiry="current_week", for_date=date.today(), bucket_interval_minutes=60)
```

`expiry` accepts an ISO date string or one of Upstox's own keywords (`current_week`/`next_week`/`far_week`/`current_month`/`next_month`/`far_month`). Note: all four of `get_oi`/`get_change_in_oi`/`get_max_pain`/`get_pcr`'s response expiry fields come back as `"DD-MM-YYYY"` (e.g. `"21-07-2026"`) — live-verified against a real account; the docs' own rendered example for `get_oi`/`get_change_in_oi` showed ISO format instead, which turned out to be wrong.

```python
await broker.market_information.get_fii_activity("NSE_FO|INDEX_OPTIONS", interval="1D")  # dict[str, list[InstitutionalActivity]]
await broker.market_information.get_dii_activity(interval="1D")                            # list[InstitutionalActivity] (NSE Cash only)
```

```python
await broker.market_information.get_futures_smartlist(asset_type="INDEX", category="TOP_TRADED")
await broker.market_information.get_options_smartlist(asset_type="STOCK", category="OI_GAINERS")
await broker.market_information.get_mtf_smartlist()
```

```python
await broker.market_information.get_market_holidays()          # list[MarketHoliday] — no auth needed
await broker.market_information.get_exchange_timings(date.today())  # list[ExchangeTiming] — no auth needed
await broker.market_information.get_market_status("NSE")        # MarketStatus
```

`get_market_holidays`/`get_exchange_timings` need **no token at all** (verified from source, same `auth_settings=[]` pattern as `historical`) — live-verified 2026-07-20 (22 real holidays for the year, real today's exchange timings across NSE/BSE/MCX/NFO/BFO/CDS/BCD/NSCOM). Real SDK quirk: the holiday response's date field is `_date` in `.to_dict()`'s output, not `date` — swagger-codegen renamed it to avoid shadowing the `datetime.date` import in that model file; the mapper reads `_date` accordingly.

### `broker.charges` — `ChargesProvider` (new core interface)

Pre-trade cost calculator — no Groww/Fyers equivalent, same `UpstoxBroker`-only placement as fundamentals/news/market_information. Works off the Analytics Token (no OAuth needed).

```python
from decimal import Decimal
from brokerkit import Product, TransactionType

charges = await broker.charges.get_brokerage(
    reliance, quantity=10, product=Product.CNC,
    transaction_type=TransactionType.BUY, price=Decimal("1300"),
)
print(charges.total, charges.taxes.stt, charges.other_charges.transaction)
```

`dp_plan` (Depository Participant charge) is only present for delivery sells per Upstox's own docs example — stays `None` otherwise, not assumed always-present.

### `broker.historical` — `HistoricalDataProvider`

```python
from datetime import datetime, timedelta
candles = await broker.historical.get_candles(reliance, start=datetime.now()-timedelta(days=10), end=datetime.now(), interval_minutes=1440)
```

**No token needed at all** — verified from source (every method in `history_v3_api.py` sets `auth_settings = []`), genuinely public data, unlike Market Quote. Supports arbitrary minute/hour/day intervals (weeks/months not wired — YAGNI, add if needed).

### `broker.streaming` — `StreamingProvider`

```python
async def on_tick(tick):
    print(tick.symbol, tick.ltp)

await broker.streaming.subscribe_ltp([reliance], on_tick)
await broker.streaming.unsubscribe_ltp([reliance])
await broker.streaming.close()
```

Wraps `MarketDataStreamerV3` (websocket + protobuf, decoded to a dict internally by the SDK — no manual byte-parsing needed, unlike Groww/Fyers). One real quirk verified from source: `connect()` spawns the websocket thread and returns immediately, with no guarantee the socket is actually open yet — this adapter waits for the SDK's own `"open"` event before the first subscribe, to avoid sending on a not-yet-ready connection.

Uses **"full" mode, not "ltpc"** — verified from the SDK's own proto that "ltpc" mode carries no cumulative volume at all (only `ltq`, the last single trade's size), unlike Groww/Fyers' basic LTP feeds. "full" mode's `vtt`/`oi` fields populate `Tick.volume`/`open_interest` properly for stocks/derivatives. Trade-off: "full" mode's per-connection limit is 2000 instrument keys (vs. "ltpc"'s 5000, per Upstox's documented subscription-limits table). Index instruments (e.g. NIFTY) use a different feed shape with no volume/OI at all — `Tick.volume`/`open_interest` correctly stay `0`/`None` for those specifically, not a bug.

`Tick.minute_ohlc` (new, Upstox-only for now — `None` on Groww/Fyers) carries Upstox's own **server-computed, continuously-updating 1-minute candle** straight from the same "full" mode feed — its `marketOHLC.ohlc` list includes both a `"1d"` (daily) and an `"I1"` (1-minute) entry per update; this adapter extracts the `"I1"` one. This means you don't need to bucket raw ticks into 1-minute bars yourself — Upstox already does it server-side; just store `tick.minute_ohlc` (keyed by instrument + its current timestamp/minute) into your timeseries DB as it updates. Available for index instruments too (unlike volume/OI), since `marketOHLC` is present in both the `MarketFullFeed` and `IndexFullFeed` shapes.

**Fyers has no equivalent** — confirmed by reading `fyers_apiv3`'s own `FyersWebsocket/map.json`: its `SymbolUpdate` feed's `open_price`/`high_price`/`low_price` are day-session level only (same fields/semantics as its REST quote), no per-minute candle concept at all. If your pipeline consumes both Upstox and Fyers, `minute_ohlc` will only ever populate for Upstox ticks — for Fyers you still need to bucket `tick.ltp`/`tick.timestamp` into 1-minute OHLC yourself (Fyers' `Tick.volume` is real cumulative day-volume already, so that part alone doesn't need aggregation).

### `broker.orders` — `OrderProvider` / `broker.portfolio` — `PortfolioProvider`

Need the OAuth token (see above) — `portfolio` also needs static IP registration (same SEBI rule as Groww/Fyers). Real SDK split verified from source: writes (`place_order`/`modify`/`cancel`) use `OrderApiV3`; single-order lookup uses `OrderApi.get_order_status` (misleadingly, `get_order_details` on the same class returns order *history*, not a snapshot). `modify()` re-sends every field (Upstox's `ModifyOrderRequest` rejects `None` for `order_type`/`validity`/`price`/`trigger_price` — verified from the SDK's own setters), so it pre-fetches the current order to backfill anything not explicitly changed, same idiom as Groww's adapter.

Order status has 17 raw values (vs. core's 6) — see `mapper.py`'s `_STATUS_MAP` for the documented reasoning behind each collapse.

## Verification status (2026-07-20)

**Live-verified, unauthenticated:** `instruments.fetch_instruments()` (real RELIANCE/NIFTY rows), `historical.get_candles()` (real recent RELIANCE candles).

**Unit/smoke-checked only (no Upstox account used yet):** auth (both paths), orders, portfolio, market, option chain, streaming, fundamentals (all 8 endpoints), news. Extend the sandbox test (`scratch_upstox.py` at the repo root) once real Upstox API credentials are available — same pattern as Groww's `scratch_orders.py`/Fyers' sandbox script.
