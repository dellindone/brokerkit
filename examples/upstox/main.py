"""Upstox — fundamentals + news + F&O analytics.

Upstox ka do-token design is adapter ki khaas baat hai:

  * Analytics Token — dashboard se banta hai, 1 saal chalta hai, read-only,
    static IP nahi chahiye. Market/historical/option-chain/fundamentals/
    news/charges/market-information sab isse chalte hain. Zero daily friction.
  * OAuth token — sirf orders/portfolio ke liye. Iska koi headless refresh
    hai hi nahi, roz asli browser login chahiye — isliye ye path
    deliberately deferred hai.

    export UPSTOX_ANALYTICS_TOKEN=...
    python examples/upstox/main.py

Sirf analytics_token dene par create() koi network call nahi karta aur
orders/portfolio set hi nahi hote (unhe access karne pe AttributeError).
"""

import asyncio
import os
from datetime import datetime, timedelta

from brokerkit import Exchange, Segment, create_broker
from brokerkit.utils.datetime import IST


async def main() -> None:
    broker = await create_broker(
        "upstox",
        analytics_token=os.environ["UPSTOX_ANALYTICS_TOKEN"],
        # Orders/portfolio chahiye to ye bhi do (roz browser login lagega):
        #   client_id=..., client_secret=..., redirect_uri=...
        # ya pehle se minted token: access_token=...
        # Sandbox mein order writes test karne ke liye: sandbox_token=...
    )
    print(f"Connected: {broker.name}")

    instruments = await broker.instruments.fetch_instruments()
    print(f"Instruments: {len(instruments)}")

    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    # Upstox har cheez apni instrument_key se address karta hai, isliye
    # exchange_token mein "NSE_EQ|INE002A01018" jaisa string aata hai —
    # baaki brokers ka numeric exchange token nahi.
    print(f"  {reliance.symbol}: key={reliance.exchange_token} isin={reliance.isin}")

    # --- fundamentals: yahi is adapter ki asli wajah hai -----------------
    profile = await broker.fundamentals.get_company_profile(reliance)
    print(f"\nSector: {profile.sector}")
    print(f"  {profile.company_profile[:100]}...")

    ratios = await broker.fundamentals.get_key_ratios(reliance)
    print(f"Key ratios: {len(ratios)} entries")
    for r in ratios[:5]:
        print(f"  {r.name}: company={r.company_value} sector={r.sector_value}")

    # Baaki 6: get_balance_sheet, get_cash_flow, get_income_statement,
    # get_share_holdings, get_corporate_actions, get_competitors.

    # --- news ------------------------------------------------------------
    articles = await broker.news.get_news([reliance])
    print(f"\nNews ({len(articles)}) — pichhle 7 din:")
    for a in articles[:3]:
        print(f"  {a.heading[:70]}")

    # --- market information: F&O analytics, kisi aur broker mein nahi ----
    nifty = next(i for i in instruments if i.symbol == "NIFTY")
    end = datetime.now(IST)
    next_expiry = min(
        i.expiry for i in instruments
        if i.instrument_type.value == "CE" and (i.underlying or "").upper() == "NIFTY"
        and i.expiry and i.expiry > end.date()
    )
    # Dhyan do: ye endpoints expiry ko "DD-MM-YYYY" STRING mein maangte
    # hain, date object mein nahi. Docs ka rendered example ISO dikhata
    # tha — wo galat nikla, asli response/param DD-MM-YYYY hai.
    expiry_str = next_expiry.strftime("%d-%m-%Y")

    pcr = await broker.market_information.get_pcr(
        nifty, expiry_str, for_date=end.date(), bucket_interval_minutes=15
    )
    print(f"\nPCR {pcr.expiry_date}: {pcr.pcr} (spot close {pcr.spot_closing_price})")

    max_pain = await broker.market_information.get_max_pain(
        nifty, expiry_str, for_date=end.date(), bucket_interval_minutes=15
    )
    print(f"Max pain: {max_pain.max_pain} (spot close {max_pain.spot_closing_price})")

    fii = await broker.market_information.get_fii_activity(segment="FUTIDX", interval="1d")
    print(f"FII activity buckets: {list(fii)}")

    # Market calendar ko token ki zaroorat hi nahi (auth_settings=[]).
    holidays = await broker.market_information.get_market_holidays()
    print(f"Holidays this year: {len(holidays)}")

    # --- historical: ismein bhi token nahi lagta -------------------------
    candles = await broker.historical.get_candles(
        reliance, end - timedelta(days=5), end, interval_minutes=24 * 60
    )
    print(f"\nDaily candles: {len(candles)}")

    # --- streaming: SIRF Upstox live minute candle deta hai --------------
    seen = 0

    def on_tick(tick):
        nonlocal seen
        seen += 1
        if seen <= 5:
            # minute_ohlc server-side computed hai — Fyers/Dhan/Angel/
            # Zerodha mein ye None rehta hai, wahan khud bucket karna padta.
            print(f"  tick {tick.symbol} {tick.ltp} vol={tick.volume} "
                  f"minute_ohlc={tick.minute_ohlc}")

    print("\n10s streaming...")
    await broker.streaming.subscribe_ltp([reliance, nifty], on_tick)
    await asyncio.sleep(10)
    print(f"  total ticks: {seen}")
    await broker.streaming.unsubscribe_ltp([reliance, nifty])

    # Note: "full" mode ki per-connection limit 2000 keys hai, aur Upstox
    # isse silently enforce karta hai — 2000 se upar wale symbols bas kabhi
    # tick nahi karte, na error aata hai na connection girta hai.

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
