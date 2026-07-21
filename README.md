# BrokerKit

One async Python interface over six Indian brokers — **Groww, Fyers, Upstox, Dhan, Angel One and Zerodha**.

Every broker ships its own SDK with its own auth flow, its own symbol format, its own units (some report prices in paise, some in rupees), its own error convention (some raise, some return a failure dict, some silently return `status: false`) and its own idea of what a "quote" contains. BrokerKit normalizes all of that behind one typed, async contract, so strategy code doesn't change when the broker does.

```python
from brokerkit import create_broker

broker = await create_broker("zerodha", api_key=..., api_secret=..., access_token=...)

instruments = await broker.instruments.fetch_instruments()
reliance = next(i for i in instruments if i.symbol == "RELIANCE")

quote = await broker.market.get_quote(reliance)
print(quote.last_price, quote.volume)

await broker.close()
```

Swap `"zerodha"` for `"fyers"` and the rest of that code is unchanged.

---

## Status

The core contract is stable across six adapters. What varies is per-broker *coverage*, and where it stops it is almost always an account-state or regulatory wall rather than missing code. Nothing in the table below is aspirational — it reflects what has actually been run against real accounts.

| | Groww | Fyers | Upstox | Dhan | Angel One | Zerodha |
|---|---|---|---|---|---|---|
| auth | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| instruments | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| market / historical | 🔒 paid | ✅ | ✅ | 🔒 paid | ✅ | 🔒 paid |
| streaming | 🔒 paid | ✅ | ✅ | 🔒 paid | ⏳ | 🔒 paid |
| portfolio | ✅ | ⏳ | 🔒 oauth | ✅ | ✅ | ✅ |
| orders (read) | ⏳ | ⏳ | 🔒 oauth | ✅ | ✅ | ✅ |
| orders (write) | 🔒 ip | 🔒 ip | ✅ sandbox | 🔒 ip | 🔒 ip | 🔒 ip |

✅ verified against a real account · ⏳ implemented, not yet exercised live · 🔒 blocked

- **paid** — the broker charges for market data (Groww ~₹499/mo, Dhan Data API, Zerodha ₹500/mo).
- **ip** — SEBI requires a registered static IP for API order placement. Only Upstox and Dhan offer a sandbox that sidesteps it; Angel One and Zerodha do not, so their write paths may stay unverifiable.
- **oauth** — Upstox's order/portfolio token needs a real browser login daily, with no headless refresh.

---

## Install

Not on PyPI yet, so install from the repo. Always install `brokerkit-core` plus the adapters you actually want — there is no need to install all six.

```bash
git clone https://github.com/dellindone/brokerkit.git
cd brokerkit
```

**Pick one of the two cases below.** The only thing that decides which is whether you need Groww *and* Fyers together.

### Case 1 — you do NOT need both Groww and Fyers (almost everyone)

One command, any combination:

```bash
pip install ./packages/brokerkit-core \
            ./packages/brokerkit-zerodha \
            ./packages/brokerkit-angelone
```

Swap in whichever adapters you want: `brokerkit-groww`, `brokerkit-fyers`, `brokerkit-upstox`, `brokerkit-dhan`, `brokerkit-angelone`, `brokerkit-zerodha`. Just don't list Groww and Fyers in the same command.

Done. `pip check` will be clean.

### Case 2 — you need both Groww and Fyers

These two cannot be resolved together in one `pip install`, so run **three commands in this order**:

```bash
# 1. everything except Groww
pip install ./packages/brokerkit-core \
            ./packages/brokerkit-fyers \
            ./packages/brokerkit-upstox \
            ./packages/brokerkit-dhan \
            ./packages/brokerkit-angelone \
            ./packages/brokerkit-zerodha

# 2. now add Groww (this pulls aiohttp forward to 3.14.x)
pip install ./packages/brokerkit-groww

# 3. put aiohttp back where Fyers needs it
pip install "aiohttp==3.9.3"
```

Then check it worked:

```bash
python -c "
from brokerkit.assembly.factory import _resolve
for n in ['groww','fyers','upstox','dhan','angelone','zerodha']:
    print(n, '->', _resolve(n).__name__)
"
```

**Expect `pip check` to complain** after Case 2 — it will say growwapi wants `aiohttp>=3.11.18` but you have 3.9.3. That warning is correct and unavoidable; the setup still works (verified end to end: both adapters resolve and both fetch their real instrument masters). Treat it as a deliberate workaround, not a supported configuration.

<details>
<summary>Why this conflict exists</summary>

It is upstream, not this project. `fyers-apiv3` pins aiohttp **exactly** (`==3.9.3` on the current 3.1.14, `==3.8.4` on older releases), while `growwapi` requires `aiohttp>=3.11.18`. No version of either satisfies both, and listing order makes no difference — both orders were tested and fail identically. In practice both SDKs run fine on 3.9.3, so the pins are stricter than the real need.

Do **not** reach for `pip install --no-deps growwapi`. `--no-deps` also skips growwapi's legitimate dependencies (pandas, nats-py, protobuf), and importing the adapter then fails with `ModuleNotFoundError: No module named 'pandas'`.
</details>

### Developing on BrokerKit itself

Add `-e` to any of the commands above for an editable install, so source edits take effect without reinstalling:

```bash
pip install -e ./packages/brokerkit-core -e ./packages/brokerkit-zerodha
```

### Once published

```bash
pip install brokerkit[zerodha]
pip install brokerkit[zerodha,upstox,dhan]
pip install brokerkit[all]
```

`brokerkit[all]` means **every adapter that can coexist in one resolution** — that is Fyers, Upstox, Dhan, Angel One and Zerodha. Groww is excluded on purpose: including it would make `[all]` fail for everyone, for the upstream reason described above. Install it explicitly with `brokerkit[groww]`, and follow Case 2 if you want it alongside Fyers.

---

## Architecture

A monorepo of independent distributions. `brokerkit-core` never imports an adapter; `create_broker("zerodha", ...)` lazily imports `brokerkit_zerodha`, which self-registers. Adding a broker touches no core code.

```
packages/
  brokerkit-core/       # the `brokerkit` package: models, interfaces, assembly
  brokerkit-groww/      # brokerkit_groww
  brokerkit-fyers/      # brokerkit_fyers
  brokerkit-upstox/     # brokerkit_upstox
  brokerkit-dhan/       # brokerkit_dhan
  brokerkit-angelone/   # brokerkit_angelone
  brokerkit-zerodha/    # brokerkit_zerodha
examples/               # one runnable example per broker
docs/ROADMAP.md         # the full build log, phase by phase
```

Hyphens are the pip distribution name, underscores the importable module — hyphens are illegal in module names.

### The contract

Every broker exposes the same seven providers:

| Attribute | Interface | What it does |
|---|---|---|
| `broker.instruments` | `InstrumentProvider` | `fetch_instruments()` → normalized master |
| `broker.orders` | `OrderProvider` | place / modify / cancel / get / list |
| `broker.portfolio` | `PortfolioProvider` | holdings, positions |
| `broker.market` | `MarketDataProvider` | quote, ltp, ohlc, option chain |
| `broker.historical` | `HistoricalDataProvider` | candles |
| `broker.streaming` | `StreamingProvider` | live tick subscription |
| `broker.auth` | `AuthProvider` | login, token lifecycle |

Everything is `async`; adapters wrap sync vendor SDKs with `asyncio.to_thread`. Models are Pydantic v2 with `Decimal` prices. State is instance-scoped, so `BrokerManager` can hold several accounts at once.

### Broker-specific extras

Capabilities only some brokers have live off the shared base rather than being forced into it:

| Broker | Extras |
|---|---|
| Upstox | `fundamentals` `news` `market_information` `charges` `risk_control` `sandbox_orders` |
| Dhan | `global_stocks` (US equities) `risk_control` `sandbox_orders` |
| Angel One | `charges` `analytics` |
| Zerodha | `charges` `gtt` |

`charges` implements a shared `ChargesProvider` interface; the rest are adapter-local because no other broker has an equivalent.

---

## Auth, per broker

| Broker | Mechanism | Daily friction |
|---|---|---|
| Groww | TOTP | none — token expires 6 AM IST, auto-refreshed |
| Fyers | TOTP + PIN | none, but a **new app** needs one browser activation first |
| Upstox | Analytics Token (data) / OAuth (orders) | none for data; OAuth needs a **daily browser login** |
| Dhan | TOTP + PIN | none — but token generation is rate-limited to 1 per 2 min |
| Angel One | TOTP + MPIN | none — native refresh-token flow |
| Zerodha | **browser only** | **a browser login every day** |

Zerodha is the outlier: Kite Connect has no TOTP and no programmatic login of any kind, and its token dies at 6 AM IST. `brokerkit_zerodha.get_access_token()` captures the redirect with a local server so it is one click, and the token can then be passed back in to skip the browser for the rest of the day.

---

## Examples

`examples/<broker>/main.py` — one per broker, each written around that broker's actual strengths, with every known wall handled explicitly. See [`examples/README.md`](examples/README.md) for the comparison tables.

---

## Two things to know if you're building a data pipeline

1. **Only Upstox provides a server-computed live 1-minute candle** (`Tick.minute_ohlc`). For Fyers, Dhan, Angel One and Zerodha it stays `None` — you aggregate ticks yourself.
2. **ISIN is the natural cross-broker join key, but Angel One's and Zerodha's masters have no ISIN column** (`isin` is always `None`). Join those on `exchange_token` instead — it matches exactly across Groww, Fyers, Dhan and Zerodha (RELIANCE is `2885` on all of them).

---

## Development

The repo's own correctness checks worth re-running after any adapter change:

- **Cross-broker instrument diff** — normalize the *same* real instruments through every adapter and compare. This is the highest-value check here: it once caught a 100x `tick_size` bug in the Upstox adapter that had been live for months and was invisible in isolation.
- **`get_type_hints` sweep** over every provider method — catches annotation breakage that Python 3.14's deferred evaluation (PEP 649) otherwise hides until runtime.
- **Dependency audit** — declared dependencies vs actually imported modules, per package.

`docs/ROADMAP.md` carries the full build log: every design decision, every SDK quirk found by reading source, and an explicit split between what is live-verified and what is still written from docs.

---

## License

MIT © 2026 Aditya Vishwakarma &lt;vaditya098@gmail.com&gt;

See [LICENSE](LICENSE).
