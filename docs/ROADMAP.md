# BrokerKit Build Roadmap

Goal for Milestone 1: **Groww working end-to-end** — authenticate, look up instruments, place/track orders, read portfolio, fetch quotes, stream ticks — through the framework's own interfaces.

Layout convention: `packages/<hyphen-name>/` is the pip distribution (owns `pyproject.toml`); the folder inside it (`brokerkit` for core, `brokerkit_<broker>` elsewhere) is the importable Python package — hyphens are illegal in module names. Code always goes in the inner underscore folder. (Inner dirs of groww/fyers/upstox/paper/replay were renamed from hyphens to underscores on 2026-07-15.)

How to use this file: work through tasks in order. Each task lists the file(s) to create and what "done" means. Ask your guide by task number when stuck (e.g. "stuck on 2.3").

Decisions already made:
- Build one broker (Groww) end-to-end first; core grows only as the integration demands.
- Groww adapter wraps the official `growwapi` SDK (not raw REST) — it's the only way to get streaming, and auth becomes trivial.
- Auth: **TOTP-only** in v1 — `GrowwAuth(api_key, totp_secret)`, both required. (Groww's UI offers TOTP token or direct access token; the static-token mode was considered and dropped from v1 for simplicity — easy to add back as an optional `access_token` param. The old key+secret/approval flow is removed from Groww's UI — do not implement it.)
- SEBI compliance (per Groww dashboard banner): a registered **static IP** is mandatory for API trading (deadline was 31 Mar 2026). API calls may be rejected from unregistered IPs — register via "Add static IP" on the dashboard if requests fail.
- Instrument interface: **thin-adapter** (reshaped 2026-07-19, user decision): single method `fetch_instruments() -> list[Instrument]` — fetch + normalize + return, **no storage in the framework** (SDK's DataFrame copy flushed after normalize). Storage/lookups/search are app-level (→ M3.5 DB store). Dropped from the ABC same day: `search`, then `get_instrument`/`get_by_token`/`refresh` (whole cache layer). Consequence for Phase 6: feed subscribe takes `list[Instrument]` from the app (model carries the exchange/segment/token triple the feed topics need — verified against GrowwFeed._get_topics); framework maps ticks only for active subscriptions.
- **Async-native**: every interface method is `async def`. Adapters wrap sync vendor SDK calls with `asyncio.to_thread(...)`. Blocking calls must never run directly inside interface methods.
- **Core models use Pydantic v2** (`pydantic>=2` is a `brokerkit-core` dependency): validation at construction, JSON serialization for the FastAPI/AI layers. Enums stay stdlib `enum.Enum`/`StrEnum`.
- **Instance-scoped state only** (keeps multi-account possible later): no module-level tokens, clients, or caches. One provider/broker instance = one account. A future `BrokerManager` composes N broker instances; deferred until after Milestone 1.

---

## Phase 1 — Auth

- [x] **1.1** `packages/brokerkit-groww/pyproject.toml` — add `growwapi` and `pyotp` deps (this package only). Install them in `.venv` and poke `GrowwAPI.get_access_token()` in a REPL to see what it returns (bare string vs object with expiry).
- [x] **1.2** `brokerkit-core/brokerkit/models/auth.py` — `AuthToken` model: token string, expiry datetime (Groww tokens die 6:00 AM IST), helper like `is_expired`.
- [x] **1.3** `brokerkit-core/brokerkit/exceptions/common.py` + `exceptions/auth.py` — a `BrokerKitError` base, then `AuthenticationError`, `TokenExpiredError`.
- [x] **1.4** `brokerkit-core/brokerkit/interfaces/auth.py` — `AuthProvider` ABC: `login() -> AuthToken`, `get_token() -> AuthToken`. (`can_refresh` removed 2026-07-15 — YAGNI while every provider is TOTP/refreshable; reintroduce if a non-refreshable auth mode appears.)
- [x] **1.5** `packages/brokerkit-groww/.../auth.py` — `GrowwAuth` (TOTP-only), verified with real credentials 2026-07-15. Leftover cleanups: remove dead `if not self.totp_secret` branch, add `can_refresh` property, split `import asyncio, pyotp`. Revisit after 1.4 to make it implement `AuthProvider` and return `AuthToken` instead of `str`.

## Phase 2 — Instruments

> Phase 2 complete 2026-07-19. (Root cause of the earlier "unsaved" re-export: top-level `__init__.py` content had been saved into `models/__init__.py`. Fixed + committed e849dc4.)

- [x] **2.1** `enums/exchange.py` + `enums/segment.py` — `Exchange`/`Segment` as **StrEnum** (NSE/BSE/MCX; CASH/FNO/COMMODITY/CURRENCY). Done, verified.
- [x] **2.2** `models/instrument.py` — `Instrument` (pydantic, Decimal tick_size; derivative fields expiry/strike/underlying dropped for v1 — YAGNI, re-add as optional when F&O comes). Done.
- [x] **2.3** `interfaces/instrument.py` — `InstrumentProvider` ABC (get_instrument, get_by_token(exchange_token, exchange, segment) — raises not returns None, search, refresh) + `exceptions/instrument.py` with `InstrumentNotFoundError`. Done, incl. top-level re-export (e849dc4).
- [x] **2.4** `packages/brokerkit-groww/.../instruments.py` — `GrowwInstruments(InstrumentProvider)` sourcing data via the SDK: `to_thread(client.get_all_instruments)` (downloads the public CSV as a str-dtype DataFrame), build own (symbol|token, exchange, segment)→Instrument dicts in one pass, skip unknown-enum rows. SDK's own lookup methods unused (no segment filter/search/refresh); `refresh()` = `client.instruments = None` + reload. SDK writes `instruments.csv` to cwd's parent — gitignore it. Done when `get_instrument("RELIANCE", NSE, CASH)` returns a populated model. Verified live 2026-07-19 (dummy token works — CSV is public; 145,746 instruments cached).
- [x] **2.5** `packages/brokerkit-groww/.../broker.py` — minimal `GrowwBroker` (pulled forward from 7.1 so framework users never import `growwapi`): `__init__(totp_key, totp_secret)` builds `GrowwAuth` internally (TOTP-only decision reaffirmed 2026-07-19 — no auth injection, no static-token mode); built as an async `create()` classmethod factory (user's improvement over the planned `connect()` — no half-constructed broker can exist): gets token, builds the one shared `GrowwAPI` client, wires `self.instruments` (+ `self.orders` since 3.7). Done: `await GrowwBroker.create(k, s)` works with zero growwapi imports in user code.

## Phase 3 — Orders

> **▶ NEXT SESSION STARTS HERE:** Phase 4 (4.1 models). **Pending user action first:** register static IP on Groww dashboard ("Add static IP") — 3.7 live test failed with "No registered IPs found for this user" (the SEBI requirement in Decisions). After registering, re-run `scratch_orders.py` (repo root, uncommitted: place after-hours LIMIT RELIANCE @1000 qty1 → get_order → cancel → list_orders) to finish 3.7 verification. Silver lining: the IP error arrived as core `OrderError` — 3.6 error translation + auth + place() path verified live 2026-07-19.

- [x] **3.0** F&O/options support in core (user decision 2026-07-19 — options trading wanted, incl. for future AI-agent consumers who need typed fields, not symbol parsing): `enums/instrument_type.py` (`InstrumentType`: EQ/FUT/CE/PE/IDX — exact CSV values, verified); `Instrument` gains optional `expiry: date`, `strike: Decimal`, `underlying: str` (None for equities) and `instrument_type` becomes the enum; Groww normalization maps expiry_date/strike_price/underlying_symbol. (Amends the 2.2 YAGNI drop — "re-add when F&O comes"; it came.)
- [x] **3.1** `brokerkit-core/brokerkit/enums/` — `order_type.py` (MARKET, LIMIT, SL, SL_M), `transaction_type.py` (BUY, SELL), `product.py` (CNC, MIS, NRML), `validity.py` (DAY, IOC), `order_status.py` (canonical 6: PENDING/OPEN/EXECUTED/CANCELLED/REJECTED/FAILED — Groww's 12 raw states collapse in the mapper). Values verified against SDK constants + docs annexure 2026-07-19; SDK extras deliberately excluded (BO/CO/MTF/ARB products, GTC/GTD/EOS validity, GTT/OCO smart orders) — unverified promises; add only when implemented+tested.
- [x] **3.2** `models/order.py` — `OrderRequest` (carries full `Instrument` object — design (b), gives mapper the symbol/exchange/segment triple free) + `Order` (flat trading_symbol/exchange/segment since it's built from broker responses). Decimal prices; `model_validator` enforces LIMIT/SL→price, SL/SL_M→trigger_price, MARKET→neither.
- [x] **3.3** `exceptions/order.py` — `OrderError` → `OrderRejectedError` → `InsufficientMarginError` (margin = a kind of rejection, so `except OrderRejectedError` catches both).
- [x] **3.4** `interfaces/order.py` — `OrderProvider` ABC. `segment: Segment` param on modify/cancel/get_order — Groww SDK requires it; core enum, so not a leak.
- [x] **3.5** `brokerkit_groww/mapper.py` — status map: 12 annexure statuses + `OPEN` (doc examples only) → canonical 6; CANCELLATION/MODIFICATION_REQUESTED→OPEN, COMPLETED/DELIVERY_AWAITED→EXECUTED; unknown status raises (loud > silent FAILED). `place_response_to_order` echoes request fields (place response is thin). `amo_status` deliberately not mapped (Groww-specific; escape hatch if ever needed: optional `raw: dict` on Order). Enum values identity-map (3.1 verified them against SDK strings).
- [x] **3.6** `brokerkit_groww/errors.py` — `groww_errors(default)` contextmanager; auth/instrument exceptions map explicitly, rest go to caller-supplied `default` (context decides domain). **Verified live**: unregistered-IP rejection surfaced as core `OrderError`.
- [x] **3.7** `brokerkit_groww/order.py` (note: singular filename, not orders.py) — `GrowwOrderProvider`, wired in `GrowwBroker.create()`. SDK quirk: `modify_order` requires quantity+order_type, so `modify()` fetches current order to fill unspecified fields; modify/cancel re-fetch via `get_order()` (thin SDK responses; correctness > latency). Decision taken: **no pre-validation** — let broker reject (freeze_quantity etc. stay dropped; revisit with M2 middleware). Code complete; **live place+cancel still unverified** — blocked on static-IP registration (see NEXT SESSION note).

## Phase 4 — Portfolio

> Margin dropped from v1 (user call 2026-07-19: "worth nahi hai") — no `Margin` model, no `margins()` on the ABC. Re-add as optional method + model if a strategy actually needs pre-trade margin checks (Groww's `get_available_margin_details` is there when wanted).

- [x] **4.1** `models/position.py` (net qty, buy/sell qty+avg from debit/credit, realised_pnl) + `models/portfolio.py` (`Holding`: demat-level, ISIN-identified, **no exchange field** — deliberate; pledged/t1 quantities kept).
- [x] **4.2** `interfaces/portfolio.py` — `PortfolioProvider` ABC: `holdings()`, `positions()` only.
- [x] **4.3** `brokerkit_groww/portfolio.py` — `GrowwPortfolio` + mapper `groww_to_holding`/`groww_to_position` (debit=buy, credit=sell), wired in `create()`. Code complete 2026-07-19; live check pending alongside the 3.7 order test (after static-IP registration).

## Phase 5 — Market Data (REST)

- [ ] **5.1** `brokerkit-core/brokerkit/models/quote.py` + `models/candle.py` — quote snapshot (LTP, OHLC, depth), historical candle.
- [ ] **5.2** `brokerkit-core/brokerkit/interfaces/market.py` + `interfaces/historical.py` — quote/LTP/OHLC (batch-aware: Groww takes up to 50 symbols per call) and historical candles.
- [ ] **5.3** `packages/brokerkit-groww/.../market.py` + `historical.py` — implement via SDK.

## Phase 6 — Streaming

- [ ] **6.1** `brokerkit-core/brokerkit/interfaces/streaming.py` — subscribe/unsubscribe by instrument, callback-based tick delivery, connection lifecycle.
- [ ] **6.2** `brokerkit-core/brokerkit/exceptions/streaming.py`.
- [ ] **6.3** `packages/brokerkit-groww/.../streaming.py` — wrap `GrowwFeed`. Done when live LTP ticks arrive through your interface during market hours.

## Phase 7 — Broker Assembly

- [ ] **7.1** `packages/brokerkit-groww/.../broker.py` — `GrowwBroker`: owns the authenticated `GrowwAPI` client, wires auth/instruments/orders/portfolio/market/streaming providers together.
- [ ] **7.2** `brokerkit-core/brokerkit/broker.py` + `registry.py` + `factory.py` — the abstract `Broker`, name→class registry, and factory so `create_broker("groww", config)` works.
- [ ] **7.3** `examples/basic/` — a runnable script: authenticate, look up an instrument, fetch a quote, show holdings. **Milestone 1 complete.**

## Later milestones (coarse — will be broken down when we get there)

- **M2 Middleware**: rate limiting (Groww: orders 10/s 250/min, live data 10/s 300/min, other 20/s 500/min), retry, auth-refresh, logging — `brokerkit-core/brokerkit/middleware/`.
- **M3 Testing package**: mocks/fixtures/contract tests in `brokerkit-testing`; contract test suite any adapter must pass.
- **M3.5 Instrument store (user idea 2026-07-19)**: DB-backed `InstrumentProvider` (SQLite first) — daily refresh job pulls each broker's master, normalizes to core `Instrument`, upserts; providers query on demand instead of holding ~500 MB in RAM. Schema keyed (broker, exchange, segment, symbol) with per-broker token columns; ISIN links the same equity across brokers. Same ABC, swap-in replacement — strategy code untouched. Build when the second broker or the data pipeline arrives.
- **M4 Paper broker**: simulated execution reusing Groww instrument data.
- **M5 Second broker (Fyers or Upstox)**: proves the abstraction; expect interface friction and fixes.
- **M6 Replay, News, AI packages.**
