"""Dhan — 2nd live execution + US equities (Global Stocks) + risk tools.

Sabse broad scope wala adapter: poore Broker contract ke upar teen
Dhan-exclusive extras — global_stocks (US equity trading, jo kisi aur
broker ke paas nahi), risk_control (kill switch + P&L auto-exit), aur
sandbox_orders.

    export DHAN_CLIENT_ID=...
    export DHAN_PIN=...
    export DHAN_TOTP_SECRET=...     # web.dhan.co -> DhanHQ APIs -> Setup TOTP
    export DHAN_ACCESS_TOKEN=...    # optional par recommended, neeche dekho
    python examples/dhan/main.py

ACCESS_TOKEN passthrough kyun: Dhan token generation ko **2 minute mein
ek baar** hi allow karta hai. Baar-baar script chalane pe rate limit lag
jaata hai, isliye ek baar token bana ke reuse karo. PIN+TOTP phir bhi
24h refresh ke liye rakhe jaate hain.
"""

import asyncio
import os

from brokerkit import BrokerKitError, Exchange, Segment, create_broker


async def main() -> None:
    broker = await create_broker(
        "dhan",
        client_id=os.environ["DHAN_CLIENT_ID"],
        pin=os.environ.get("DHAN_PIN"),
        totp_secret=os.environ.get("DHAN_TOTP_SECRET"),
        access_token=os.environ.get("DHAN_ACCESS_TOKEN"),
        # sandbox_access_token=... -> broker.sandbox_orders wire ho jaata hai
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
    # Dhan ke master mein tick_size PAISE mein hai — adapter /100 karta hai.
    print(f"  {reliance.symbol}: tick={reliance.tick_size} isin={reliance.isin}")

    # --- portfolio -------------------------------------------------------
    # Dhan khaali holdings ko *failure envelope* (DH-1111) bana ke bhejta
    # hai, 200-with-[] nahi. Adapter usse [] mein translate karta hai.
    holdings = await broker.portfolio.holdings()
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price}")

    print(f"Orders today: {len(await broker.orders.list_orders())}")

    # --- Global Stocks: US equities, kisi aur adapter mein nahi ----------
    # Core models isse represent nahi kar sakte (fractional quantity, USD,
    # INX_EQ segment), isliye iske apne adapter-local models hain.
    us = await broker.global_stocks.fetch_instruments()
    print(f"\nUS instruments: {len(us)}")
    aapl = next((i for i in us if i.symbol == "AAPL"), None)
    if aapl:
        print(f"  AAPL: id={aapl.security_id} exchange={aapl.exchange}")

    status = await broker.global_stocks.market_status()
    print(f"  US market status: {status}")

    try:
        # US trading account pe activate hona chahiye, warna INX-1007.
        print(f"  US holdings: {len(await broker.global_stocks.holdings())}")
    except BrokerKitError as e:
        print(f"  US holdings skip (account activation?): {e}")

    # --- risk control: kill switch + P&L auto-exit -----------------------
    # Dhan ka kill switch ACCOUNT-WIDE hai (Upstox ka per-segment hai).
    print(f"\nKill switch: {await broker.risk_control.kill_switch_status()}")
    print(f"P&L auto-exit: {await broker.risk_control.get_pnl_exit()}")

    # --- market data: paid Data API subscription chahiye -----------------
    try:
        quote = await broker.market.get_quote(reliance)
        print(f"\nLTP: {quote.last_price}")
    except BrokerKitError as e:
        # Bina subscription ke historical DH-902 deta hai aur marketfeed
        # HTTP 451. Ye account-state wall hai, adapter ka bug nahi.
        print(f"\nMarket data skip (Data API subscription?): {e}")

    # Order writes ke do raaste: real account (SEBI static IP chahiye) ya
    # sandbox_access_token de kar broker.sandbox_orders (IP wall bypass).
    # sandbox_orders jaan-boojh kar alag attribute hai — broker.orders se
    # kabhi merge nahi hota, taaki real aur sandbox order confuse na ho.

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
