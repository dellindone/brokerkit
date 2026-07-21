"""Groww — live execution (agents yahin se orders bhejte hain).

Ye stack ka pehla broker hai aur live-money account yahin hai. Auth sabse
simple hai: sirf TOTP, aur token ka expiry deterministic hai (roz 6:00 AM
IST), isliye background refresh loop bilkul reliably chalta hai.

    export GROWW_API_KEY=...      # TOTP api key
    export GROWW_TOTP_SECRET=...
    python examples/groww/main.py

Do dashboard actions jo Groww pe pending reh sakte hain:
  1. Static IP register karo -> order placement unblock hota hai (SEBI rule)
  2. Paid live-data plan (~Rs 499/mo) -> quote/LTP/candles/streaming unblock
Dono account-state walls hain, adapter ke bug nahi.
"""

import asyncio
import os
from datetime import datetime, timedelta

from brokerkit import BrokerKitError, Exchange, Segment, create_broker
from brokerkit.utils.datetime import IST


async def main() -> None:
    broker = await create_broker(
        "groww",
        totp_key=os.environ["GROWW_API_KEY"],
        totp_secret=os.environ["GROWW_TOTP_SECRET"],
    )
    print(f"Connected: {broker.name}")

    # Instrument interface jaan-boojh kar THIN hai: fetch + normalize +
    # return, bas. Framework kuch cache/store nahi karta — filtering aur
    # storage app ka kaam hai.
    instruments = await broker.instruments.fetch_instruments()
    print(f"Instruments: {len(instruments)}")

    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    print(f"  {reliance.name}: isin={reliance.isin} token={reliance.exchange_token}")

    # --- portfolio: bina static IP ke bhi chalta hai ---------------------
    holdings = await broker.portfolio.holdings()
    print(f"\nHoldings ({len(holdings)}):")
    for h in holdings:
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price}")

    positions = await broker.portfolio.positions()
    print(f"Positions ({len(positions)}):")
    for p in positions:
        print(f"  {p.trading_symbol}: qty={p.quantity} pnl={p.realised_pnl}")

    # --- market data: paid data subscription chahiye ---------------------
    try:
        quote = await broker.market.get_quote(reliance)
        print(f"\nLTP: {quote.last_price}  OHLC: {quote.ohlc}")

        end = datetime.now(IST)
        candles = await broker.historical.get_candles(
            reliance, end - timedelta(days=5), end, interval_minutes=24 * 60
        )
        print(f"Daily candles: {len(candles)}")
    except BrokerKitError as e:
        # Subscription na ho to "Access forbidden" milta hai.
        print(f"\nMarket data skip (data subscription?): {e}")

    # --- orders ----------------------------------------------------------
    # Order placement ke liye static IP registered hona chahiye, warna
    # "No registered IPs found" aata hai — jo adapter core OrderError bana
    # ke deta hai. Read-only list hamesha chalti hai:
    print(f"\nOrders today: {len(await broker.orders.list_orders())}")

    # Order bhejne ka shape:
    #
    #     from brokerkit.models.order import OrderRequest
    #     from brokerkit.enums import OrderType, Product, TransactionType
    #
    #     order = await broker.orders.place_order(OrderRequest(
    #         instrument=reliance,
    #         transaction_type=TransactionType.BUY,
    #         order_type=OrderType.LIMIT,
    #         quantity=1,
    #         product=Product.CNC,
    #         price=Decimal("1400"),
    #     ))
    #
    # Dhyan rahe: order idempotency abhi implement nahi hui (Groww ka
    # order_reference_id use nahi ho raha), to timeout ke baad retry
    # karne se order double lag sakta hai.

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
