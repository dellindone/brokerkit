"""Angel One (SmartAPI) — 3rd live execution + 2nd FREE data source.

Angel ka data free hai (Fyers ki tarah, Groww/Dhan ki tarah paid nahi),
isliye market/historical/option-chain sab bina subscription ke chalte hain.

    export ANGEL_API_KEY=...        # smartapi.angelone.in pe app banao
    export ANGEL_CLIENT_CODE=...    # e.g. A123456
    export ANGEL_MPIN=...           # API login MPIN maangta hai, web password nahi
    export ANGEL_TOTP_SECRET=...    # Profile -> Settings -> TOTP
    python examples/angelone/main.py

Auth ki khaas baat: ye project ka ekmatra broker hai jiske paas ASLI
refresh-token endpoint hai (generateToken) — baaki sab poora fresh login
dobara chalate hain. Iski wajah bhi hai: Angel ka jwt **wall-clock
boundary** pe marta hai, fixed duration ke baad nahi. Subah login karo to
poora din chalta hai, 11:30 PM ko karo to aadha ghanta. Isliye adapter
token ka apna exp claim decode karta hai, koi duration assume nahi karta.

Isi wajah se yahan token passthrough deliberately NAHI hai — pasted token
minutes mein baasi ho jaata hai, to chaaron credentials mandatory hain.
"""

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal

from brokerkit import Exchange, InstrumentType, Segment, create_broker
from brokerkit.enums import Product, TransactionType
from brokerkit.utils.datetime import IST


async def main() -> None:
    broker = await create_broker(
        "angelone",
        api_key=os.environ["ANGEL_API_KEY"],
        client_code=os.environ["ANGEL_CLIENT_CODE"],
        mpin=os.environ["ANGEL_MPIN"],
        totp_secret=os.environ["ANGEL_TOTP_SECRET"],
    )
    print(f"Connected: {broker.name}")

    instruments = await broker.instruments.fetch_instruments()
    print(f"Instruments: {len(instruments)}")

    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE-EQ"       # Angel bhi suffix lagata hai
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    nifty = next(
        i for i in instruments
        if i.instrument_type is InstrumentType.IDX and i.symbol.upper() == "NIFTY 50"
    )
    # Angel ke master mein strike AUR tick_size dono paise mein hain
    # (adapter /100 karta hai), aur ISIN column hai hi nahi — isliye
    # isin hamesha None. Cross-broker join ke liye exchange_token use karo.
    print(f"  {reliance.symbol}: tick={reliance.tick_size} isin={reliance.isin} "
          f"token={reliance.exchange_token}")

    # --- market data (free) ----------------------------------------------
    ltp = await broker.market.get_ltp([reliance, nifty])
    print(f"\nLTP: { {k: str(v) for k, v in ltp.items()} }")

    quote = await broker.market.get_quote(reliance)
    print(f"{reliance.symbol}: LTP {quote.last_price} vol {quote.volume}")
    # Angel depth ko 5 levels tak zero-PAD karta hai; adapter padding
    # nikaal deta hai warna ask_price Rs 0 aa jaata. Aur equity ka
    # opnInterest junk hota hai, isliye FNO/COMMODITY ke bahar OI null hai.
    print(f"  bid {quote.bid_price} / ask {quote.ask_price}  oi={quote.open_interest}")

    # --- historical -------------------------------------------------------
    end = datetime.now(IST)
    candles = await broker.historical.get_candles(
        reliance, end - timedelta(days=5), end, interval_minutes=24 * 60
    )
    print(f"\nDaily candles: {len(candles)}")

    # --- option chain: Angel ke paas server-side endpoint NAHI hai --------
    # Adapter khud assemble karta hai: master filter -> spot ke aas-paas ke
    # strikes -> FULL quotes -> alag optionGreek endpoint se greeks merge.
    expiries = await broker.market.expiry_list(nifty)
    future = [e for e in expiries if e > end.date()]
    expiry = future[1] if len(future) > 1 else future[0]
    # Sanity check ke liye AGLI expiry lo — same-day expiry pe saare greeks
    # asli mein 0.0 aate hain (options expire ho chuke hote hain), jo bug
    # jaisa dikhta hai par hota nahi.
    chain = await broker.market.get_option_chain(nifty, expiry, strike_count=4)
    print(f"\nOption chain {expiry} (spot {chain.underlying_ltp}):")
    for s in chain.strikes:
        g = s.call.greeks if s.call else None
        print(f"  {s.strike}: CE {s.call.ltp if s.call else '-'} "
              f"delta={g.delta if g else '-'} iv={g.iv if g else '-'}")

    # --- portfolio + orders ----------------------------------------------
    holdings = await broker.portfolio.holdings()
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        # ISIN master mein nahi hai par holdings response mein aata hai.
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price} isin={h.isin}")

    print(f"Orders today: {len(await broker.orders.list_orders())}")

    # --- charges (core ChargesProvider) ----------------------------------
    charges = await broker.charges.get_brokerage(
        reliance, quantity=10, product=Product.CNC,
        transaction_type=TransactionType.BUY, price=Decimal("1400"),
    )
    print(f"\nCharges: total={charges.total} brokerage={charges.brokerage} "
          f"stt={charges.taxes.stt}")

    # --- analytics: Angel-specific, adapter-local ------------------------
    # Ye raw payload lautate hain (typed nahi) — inki shape auth-gated hai
    # aur live verify nahi hui, isliye docs se type karke galat parse karne
    # se behtar hai raw dena.
    print(f"\nPCR: {await broker.analytics.put_call_ratio()}")
    gl = await broker.analytics.gainers_losers(
        datatype="PercPriceGainers", expirytype="NEAR"
    )
    print(f"Gainers: {gl}")
    greeks = await broker.analytics.option_greek(name="NIFTY", expiry=expiry)
    print(f"Greeks rows: {len(greeks) if greeks else 0}")
    # Baaki: oi_buildup(expirytype, datatype), nse_intraday, bse_intraday

    # Order writes SEBI static IP maangte hain, aur Angel ka koi public
    # sandbox nahi hai — to ye path shayad unverifiable hi rahega.

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
