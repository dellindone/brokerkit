# BrokerKit examples

Har broker ka apna example: `examples/<broker>/main.py`. Sab runnable hain, credentials env vars se aate hain.

`examples/basic/` framework ka quick-start hai (Groww ke against) — per-broker examples uske neeche detail mein jaate hain.

## Kaunsa broker kis kaam ke liye

| Broker | Role | Extras (shared `Broker` base se bahar) |
|---|---|---|
| **Groww** | Live execution — agents yahin se orders bhejte hain | — |
| **Fyers** | Primary **free** data source (market/historical/streaming) | — |
| **Upstox** | **Fundamentals + news**; F&O analytics | `fundamentals` `news` `market_information` `charges` `risk_control` `sandbox_orders` |
| **Dhan** | 2nd live execution + **US equities** + risk tools | `global_stocks` `risk_control` `sandbox_orders` |
| **Angel One** | 3rd live execution + 2nd **free** data source | `charges` `analytics` |
| **Zerodha** | 4th live execution + charges + **GTT** | `charges` `gtt` |

## Auth ek line mein

| Broker | Kaise | Daily friction |
|---|---|---|
| Groww | TOTP | koi nahi (6 AM IST auto-refresh) |
| Fyers | TOTP + PIN | koi nahi — par **naye app pe ek baar** `get_access_token()` browser se chalana padta hai |
| Upstox | Analytics Token (data), OAuth (orders/portfolio) | data pe koi nahi; **OAuth roz browser** maangta hai |
| Dhan | TOTP + PIN | koi nahi — par token generation **2 min mein 1 baar** hi hota hai, isliye passthrough use karo |
| Angel One | TOTP + MPIN | koi nahi (native refresh-token flow) — **jwt wall-clock boundary pe marta hai**, fixed duration nahi |
| Zerodha | **sirf browser** — koi TOTP/programmatic login hai hi nahi | **roz ek browser login** (token 6 AM IST par marta hai) |

## Kya live-verified hai, kya blocked

Ye honest status hai — "blocked" ka matlab bug nahi, account-state ya regulatory wall hai.

| | Groww | Fyers | Upstox | Dhan | Angel | Zerodha |
|---|---|---|---|---|---|---|
| auth | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| instruments | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| market / historical | 🔒 paid | ✅ | ✅ | 🔒 paid | ✅ | 🔒 paid |
| streaming | 🔒 paid | ✅ | ✅ | 🔒 paid | ⏳ | 🔒 paid |
| portfolio | ✅ | ⏳ | 🔒 OAuth | ✅ | ✅ | ✅ |
| orders (read) | ⏳ | ⏳ | 🔒 OAuth | ✅ | ✅ | ✅ |
| orders (write) | 🔒 IP | 🔒 IP | ✅ sandbox | 🔒 IP | 🔒 IP | 🔒 IP |

✅ live-verified · ⏳ likha hai par live nahi chala · 🔒 wall (paid = data subscription, IP = SEBI static IP, OAuth = daily browser login)

**Order writes har jagah SEBI static IP maangte hain.** Sirf Upstox aur Dhan ke paas sandbox hai jo is deewar ko bypass karta hai; Angel aur Zerodha ke paas koi sandbox nahi, to wahan writes shayad unverifiable hi rahenge.

## Data pipeline ke liye do gotchas

1. **Live 1-minute candle sirf Upstox deta hai** (`Tick.minute_ohlc`, server-side computed). Fyers/Dhan/Angel/Zerodha pe wo `None` rehta hai — waha ticks khud bucket karne padenge.
2. **ISIN cross-broker join key hai, par Angel aur Zerodha ke masters mein ISIN column hai hi nahi** (`isin=None`). Unke liye `exchange_token` pe join karo — wo Fyers/Dhan/Groww ke saath exactly match karta hai (RELIANCE 2885).
