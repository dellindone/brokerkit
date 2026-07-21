# brokerkit-core

The framework half of [BrokerKit](https://github.com/dellindone/brokerkit): the models, the interfaces every broker adapter implements, and the assembly layer that resolves `create_broker("zerodha", ...)` to a live, authenticated broker.

This package ships **no broker integrations**. Install it alongside at least one adapter.

```bash
pip install brokerkit-core brokerkit-zerodha
```

Available adapters: `brokerkit-groww`, `brokerkit-fyers`, `brokerkit-upstox`, `brokerkit-dhan`, `brokerkit-angelone`, `brokerkit-zerodha`.

## The idea

Every Indian broker ships its own SDK with its own auth flow, symbol format, units (some report prices in paise, some in rupees), error convention (some raise, some return a failure dict, some return `status: false` and only log it) and its own idea of what a "quote" contains. `brokerkit-core` defines one typed, async contract; each adapter absorbs its broker's quirks behind it.

```python
from brokerkit import create_broker

broker = await create_broker("zerodha", api_key=..., api_secret=..., access_token=...)

instruments = await broker.instruments.fetch_instruments()
reliance = next(i for i in instruments if i.symbol == "RELIANCE")

quote = await broker.market.get_quote(reliance)
print(quote.last_price, quote.volume)

await broker.close()
```

Swap `"zerodha"` for `"fyers"` and nothing else changes.

## The contract

Every broker exposes the same providers:

| Attribute | Interface | Methods |
|---|---|---|
| `broker.auth` | `AuthProvider` | `login`, `get_token` |
| `broker.instruments` | `InstrumentProvider` | `fetch_instruments` |
| `broker.orders` | `OrderProvider` | `place_order`, `modify`, `cancel`, `get_order`, `list_orders` |
| `broker.portfolio` | `PortfolioProvider` | `holdings`, `positions` |
| `broker.market` | `MarketDataProvider` | `get_quote`, `get_ltp`, `get_ohlc`, `get_option_chain` |
| `broker.historical` | `HistoricalDataProvider` | `get_candles` |
| `broker.streaming` | `StreamingProvider` | `subscribe_ltp`, `unsubscribe_ltp`, `close` |

Plus three interfaces that only some brokers implement, deliberately kept off the shared `Broker` base so no broker is forced to carry a hole: `ChargesProvider`, `FundamentalsProvider`, `NewsProvider`, `MarketInformationProvider`.

## Design decisions worth knowing

- **Async-native.** Every interface method is `async def`. Adapters wrap sync vendor SDKs with `asyncio.to_thread`; blocking calls never run inside an interface method.
- **Pydantic v2 models, `Decimal` prices.** Validation at construction, JSON-serializable for API/agent layers. Enums are stdlib `StrEnum`.
- **Instruments are a thin adapter, not a store.** `fetch_instruments()` downloads, normalizes and returns — the framework holds no cache, no indexes, no lookups. Storage and querying belong to your app. Calling it again re-downloads, because brokers update masters daily.
- **Instance-scoped state only.** No module-level tokens, clients or caches, so one process can hold several accounts. `BrokerManager` composes N named brokers on top of that.
- **Adapters are plugins.** Core never imports an adapter. `create_broker("dhan", ...)` lazily imports `brokerkit_dhan`, whose `Broker` subclass self-registers via `__init_subclass__`. Adding a broker touches no core code.

## Models

`Instrument`, `Order` / `OrderRequest`, `Position`, `Holding`, `Quote` / `Ohlc` / `DepthLevel`, `Candle`, `Tick`, `OptionChain` / `OptionContract` / `OptionGreeks`, `BrokerageCharges`, and the fundamentals/news/market-information models.

Two cross-broker facts these encode:

- **`Tick.minute_ohlc` only ever populates for Upstox** — it is the one broker whose feed computes a live 1-minute candle server-side. Everywhere else it stays `None` and you aggregate ticks yourself.
- **`Instrument.isin` is `None` for Angel One and Zerodha** — their instrument masters have no ISIN column at all. ISIN is the natural cross-broker join key for equities, so join those two on `exchange_token` instead; it matches exactly across Groww, Fyers, Dhan and Zerodha.

## Multiple accounts

```python
from brokerkit import BrokerManager

manager = BrokerManager()
await manager.add("main", "zerodha", api_key=..., api_secret=..., access_token=...)
await manager.add("data", "fyers", client_id=..., secret_key=..., ...)

quote = await manager["data"].market.get_quote(instrument)
await manager.close_all()
```

## License

MIT © 2026 Aditya Vishwakarma
