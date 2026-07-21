"""Zerodha (Kite Connect) — 4th live-execution account + charges + GTT.

Kite ka koi programmatic login hai hi nahi — na TOTP, na password grant.
Token roz browser se banana padta hai aur agle din 6:00 AM IST par mar
jaata hai. Isliye do step hain:

    # 1) din mein ek baar — browser khulega, token print hoga
    python -m brokerkit_zerodha.login_helper <api_key> <api_secret> http://127.0.0.1:5001/

    # 2) us token ko reuse karo
    export ZERODHA_API_KEY=...
    export ZERODHA_API_SECRET=...
    export ZERODHA_ACCESS_TOKEN=...
    python examples/zerodha/main.py

Plan note: free Personal plan mein orders/GTT/portfolio/margins hain par
market data aur historical BILKUL nahi — unke liye Rs 500/mo Connect plan
chahiye. Ye Groww/Dhan se ulta hai (wahan trading free, data paid) — yahan
execution free hai aur data paid.
"""

import asyncio
import os
from decimal import Decimal

from brokerkit import BrokerKitError, Exchange, Segment, create_broker
from brokerkit.enums import Product, TransactionType


async def main() -> None:
    broker = await create_broker(
        "zerodha",
        api_key=os.environ["ZERODHA_API_KEY"],
        api_secret=os.environ["ZERODHA_API_SECRET"],
        # access_token de diya to browser nahi khulega. Na do, aur
        # redirect_uri de do, to create() khud browser login chala dega.
        access_token=os.environ.get("ZERODHA_ACCESS_TOKEN"),
        redirect_uri=os.environ.get("ZERODHA_REDIRECT_URI", "http://127.0.0.1:5001/"),
    )
    print(f"Connected: {broker.name}")

    # --- instruments (public CSV, auth ki zaroorat bhi nahi) --------------
    instruments = await broker.instruments.fetch_instruments()
    print(f"Instruments: {len(instruments)}")

    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    # Kite ke master mein tick/strike pehle se RUPEES mein hain — Dhan/Angel/
    # Upstox ki tarah /100 karne ki zaroorat nahi.
    print(f"  {reliance.symbol}: tick={reliance.tick_size} token={reliance.exchange_token}")

    # Index rows ka instrument_type bhi "EQ" hota hai — inhe sirf
    # segment == INDICES se pehchana ja sakta hai, isliye adapter
    # InstrumentType.IDX set karta hai.
    nifty = next(i for i in instruments if i.symbol == "NIFTY 50")
    print(f"  {nifty.symbol}: type={nifty.instrument_type}")

    # --- portfolio + orders (free plan mein bhi chalte hain) -------------
    holdings = await broker.portfolio.holdings()
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price}")

    orders = await broker.orders.list_orders()
    print(f"Orders today ({len(orders)}):")
    for o in orders:
        print(f"  {o.order_id} {o.trading_symbol} {o.status} {o.quantity}@{o.price}")

    # --- charges: pre-trade cost estimate (free plan pe chalta hai) ------
    charges = await broker.charges.get_brokerage(
        reliance, quantity=10, product=Product.CNC,
        transaction_type=TransactionType.BUY, price=Decimal("1400"),
    )
    print(f"\n10 share BUY ka kharcha: total={charges.total}")
    print(f"  brokerage={charges.brokerage} stt={charges.taxes.stt} "
          f"gst={charges.taxes.gst} stamp={charges.taxes.stamp_duty}")

    # --- GTT: Zerodha-exclusive, kisi aur adapter mein nahi --------------
    triggers = await broker.gtt.list_triggers()
    print(f"\nGTTs ({len(triggers)}):")
    for t in triggers:
        print(f"  #{t.trigger_id} {t.trading_symbol} {t.trigger_type} "
              f"{t.status} @ {t.trigger_values}")

    # GTT banane ka shape aisa hota (write hai, isliye SEBI static IP
    # chahiye — Zerodha ka koi sandbox nahi hai jo isse bypass kare):
    #
    #     from brokerkit_zerodha import GttLeg
    #     await broker.gtt.place(
    #         reliance,
    #         trigger_values=[Decimal("1500")],
    #         last_price=Decimal("1400"),   # abhi ka LTP, Kite validate karta hai
    #         legs=[GttLeg(transaction_type=TransactionType.SELL,
    #                      quantity=1, price=Decimal("1500"))],
    #     )
    #
    # OCO (stop-loss + target ek saath) ke liye trigger_type="two-leg" aur
    # do trigger_values + do legs, ascending order mein.

    # --- market data: Rs 500/mo Connect plan chahiye ---------------------
    try:
        quote = await broker.market.get_quote(reliance)
        print(f"\nLTP: {quote.last_price}  volume: {quote.volume}")
        print(f"  bid {quote.bid_price} / ask {quote.ask_price}, "
              f"depth {len(quote.buy_depth)}x{len(quote.sell_depth)}")
    except BrokerKitError as e:
        # Free Personal plan pe ye "Insufficient permission" dega. Auth
        # theek hai — sirf subscription nahi hai (portfolio upar chal gaya
        # usi token se, wahi iska proof hai).
        print(f"\nMarket data skip: {e}")

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
