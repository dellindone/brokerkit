"""Fyers — primary FREE data source (market / historical / streaming).

Fyers is stack mein isliye hai ki iska market, historical aur streaming
data free hai (Groww/Dhan ki tarah paid subscription nahi). Poora Broker
contract phir bhi bana hua hai — data-only shortcut nahi liya gaya.

    export FYERS_CLIENT_ID=...      # e.g. XC4EOD67IM-100
    export FYERS_SECRET_KEY=...
    export FYERS_REDIRECT_URI=...   # app pe registered wala, exactly
    export FYERS_ID=...             # login id, e.g. XA12345
    export FYERS_TOTP_SECRET=...
    export FYERS_PIN=...
    python examples/fyers/main.py

EK BAAR ka setup, naye app ke liye: brand-new Fyers app pe TOTP login tab
tak kaam nahi karta jab tak ek baar official browser auth na ho jaaye
(warna "invalid totp" milta hai). Isliye pehli baar:

    from brokerkit_fyers import get_access_token
    get_access_token(client_id, secret_key, redirect_uri)

Uske baad TOTP+PIN auto-login har baar chalta hai, zero manual step.
"""

import asyncio
import os
from datetime import datetime, timedelta

from brokerkit import Exchange, Segment, create_broker
from brokerkit.utils.datetime import IST


async def main() -> None:
    broker = await create_broker(
        "fyers",
        client_id=os.environ["FYERS_CLIENT_ID"],
        secret_key=os.environ["FYERS_SECRET_KEY"],
        redirect_uri=os.environ["FYERS_REDIRECT_URI"],
        fy_id=os.environ["FYERS_ID"],
        totp_secret=os.environ["FYERS_TOTP_SECRET"],
        pin=os.environ["FYERS_PIN"],
    )
    print(f"Connected: {broker.name}")

    instruments = await broker.instruments.fetch_instruments()
    print(f"Instruments: {len(instruments)}")

    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE-EQ"       # Fyers apna suffix lagata hai
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    nifty = next(i for i in instruments if i.symbol == "NIFTY50-INDEX")

    # --- market data: yahi is adapter ki asli wajah hai ------------------
    quote = await broker.market.get_quote(reliance)
    print(f"\n{reliance.symbol}: LTP {quote.last_price}  vol {quote.volume}")
    print(f"  OHLC {quote.ohlc}")

    ltp = await broker.market.get_ltp([reliance, nifty])
    print(f"  batch LTP: { {k: str(v) for k, v in ltp.items()} }")

    # --- historical ------------------------------------------------------
    end = datetime.now(IST)
    candles = await broker.historical.get_candles(
        reliance, end - timedelta(days=5), end, interval_minutes=24 * 60
    )
    print(f"\nDaily candles: {len(candles)}; last close {candles[-1].close if candles else '-'}")

    # --- option chain (Fyers greeks deta hai — Zerodha/Groww nahi dete) --
    expiry = next(
        i.expiry for i in instruments
        if i.instrument_type.value == "CE" and (i.name or "").upper() == "NIFTY"
        and i.expiry and i.expiry > end.date()
    )
    chain = await broker.market.get_option_chain(nifty, expiry, strike_count=4)
    print(f"\nOption chain {expiry} (spot {chain.underlying_ltp}):")
    for s in chain.strikes:
        g = s.call.greeks if s.call else None
        print(f"  {s.strike}: CE {s.call.ltp if s.call else '-'} "
              f"delta={g.delta if g else '-'}")

    # --- portfolio -------------------------------------------------------
    holdings = await broker.portfolio.holdings()
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        # Fyers holdings mein ISIN nahi aata — isin hamesha None rahega.
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price}")

    # --- streaming -------------------------------------------------------
    # NOTE: FyersDataSocket process-wide SINGLETON hai — ek hi process mein
    # doosra Fyers feed banane se pehle wala connection hijack ho jaata.
    # Adapter isse detect karke StreamingError raise karta hai.
    seen = 0

    def on_tick(tick):
        nonlocal seen
        seen += 1
        if seen <= 5:
            # minute_ohlc yahan hamesha None rahega — Fyers ke feed mein
            # server-side minute candle hai hi nahi (sirf Upstox deta hai).
            print(f"  tick {tick.symbol} {tick.ltp} vol={tick.volume}")

    print("\n10s streaming...")
    await broker.streaming.subscribe_ltp([reliance, nifty], on_tick)
    await asyncio.sleep(10)
    print(f"  total ticks: {seen}")
    await broker.streaming.unsubscribe_ltp([reliance, nifty])

    # Order writes SEBI static IP maangte hain (dashboard pe register karo).
    # list_orders() read-only hai, chalta hai:
    print(f"\nOrders today: {len(await broker.orders.list_orders())}")

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
