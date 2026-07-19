# BrokerKit Build Roadmap

Goal for Milestone 1: **Groww working end-to-end** — authenticate, look up instruments, place/track orders, read portfolio, fetch quotes, stream ticks — through the framework's own interfaces.

Layout convention: `packages/<hyphen-name>/` is the pip distribution (owns `pyproject.toml`); the folder inside it (`brokerkit` for core, `brokerkit_<broker>` elsewhere) is the importable Python package — hyphens are illegal in module names. Code always goes in the inner underscore folder. (Inner dirs of groww/fyers/upstox/paper/replay were renamed from hyphens to underscores on 2026-07-15.)

How to use this file: work through tasks in order. Each task lists the file(s) to create and what "done" means. Ask your guide by task number when stuck (e.g. "stuck on 2.3").

Decisions already made:
- Build one broker (Groww) end-to-end first; core grows only as the integration demands.
- Groww adapter wraps the official `growwapi` SDK (not raw REST) — it's the only way to get streaming, and auth becomes trivial.
- Auth: **TOTP-only** in v1 — `GrowwAuth(api_key, totp_secret)`, both required. (Groww's UI offers TOTP token or direct access token; the static-token mode was considered and dropped from v1 for simplicity — easy to add back as an optional `access_token` param. The old key+secret/approval flow is removed from Groww's UI — do not implement it.)
- SEBI compliance (per Groww dashboard banner): a registered **static IP** is mandatory for API trading (deadline was 31 Mar 2026). API calls may be rejected from unregistered IPs — register via "Add static IP" on the dashboard if requests fail.
- Instrument interface: minimal — `get_instrument`, `get_by_token`, `search`, `refresh`.
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

## Phase 3 — Orders

> **▶ NEXT SESSION STARTS HERE:** 3.1 — order enums in `brokerkit-core`.

- [ ] **3.1** `brokerkit-core/brokerkit/enums/` — `order_type.py` (MARKET, LIMIT, SL, SL_M), `transaction_type.py` (BUY, SELL), `product.py` (CNC, MIS, NRML), `validity.py` (DAY, IOC), `order_status.py`.
- [ ] **3.2** `brokerkit-core/brokerkit/models/order.py` — `OrderRequest` (what a caller submits) and `Order` (what the broker reports back: ids, status, filled qty, avg price).
- [ ] **3.3** `brokerkit-core/brokerkit/exceptions/order.py` — `OrderError`, `OrderRejectedError`, `InsufficientMarginError`.
- [ ] **3.4** `brokerkit-core/brokerkit/interfaces/order.py` — `OrderProvider` ABC: place, modify, cancel, get_order, list_orders.
- [ ] **3.5** `packages/brokerkit-groww/.../mapper.py` — enum + field translation between core models and Groww SDK dicts. Start with order mappings; grows in later phases.
- [ ] **3.6** `packages/brokerkit-groww/.../errors.py` — map growwapi exceptions → core exceptions.
- [ ] **3.7** `packages/brokerkit-groww/.../orders.py` — `GrowwOrderProvider`. Done when you can place + cancel a real (or after-hours rejected) order through the interface.

## Phase 4 — Portfolio & Margins

- [ ] **4.1** `brokerkit-core/brokerkit/models/` — `position.py`, `portfolio.py` (holdings), `margin.py`.
- [ ] **4.2** `brokerkit-core/brokerkit/interfaces/portfolio.py` — holdings, positions, margins methods.
- [ ] **4.3** `packages/brokerkit-groww/.../portfolio.py` — implement via SDK; extend mapper.

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
- **M4 Paper broker**: simulated execution reusing Groww instrument data.
- **M5 Second broker (Fyers or Upstox)**: proves the abstraction; expect interface friction and fixes.
- **M6 Replay, News, AI packages.**
