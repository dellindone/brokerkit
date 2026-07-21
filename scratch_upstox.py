"""Live sandbox script for the Upstox adapter — run manually with real
credentials once available (same role as Groww's scratch_orders.py /
Fyers' sandbox test). Not part of the automated test suite.

Orders are deliberately NOT tested here — placing/modifying/cancelling
needs static IP registration on the Upstox dashboard (same SEBI rule that
blocked Groww/Fyers), so there's nothing to verify yet. Everything else
runs.

Reads credentials from environment variables (never hardcode secrets in
this file):

    export UPSTOX_ANALYTICS_TOKEN="..."        # dashboard Analytics tab — enough for instruments/historical/market/fundamentals/news/streaming
    export UPSTOX_CLIENT_ID="..."               # only needed for portfolio (opens a real browser login)
    export UPSTOX_CLIENT_SECRET="..."
    export UPSTOX_REDIRECT_URI="http://127.0.0.1:5000/"

    python scratch_upstox.py
"""

import asyncio
import os
import traceback
from datetime import datetime, timedelta

from brokerkit import Exchange, Segment, create_broker

ANALYTICS_TOKEN = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
CLIENT_ID = os.environ.get("UPSTOX_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("UPSTOX_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("UPSTOX_REDIRECT_URI", "")


async def _step(label, coro):
    print(f"\n--- {label} ---")
    try:
        result = await coro
        print(result)
        return result
    except Exception:
        print(f"FAILED: {label}")
        traceback.print_exc()
        return None


async def main():
    kwargs = {}
    if ANALYTICS_TOKEN:
        kwargs["analytics_token"] = ANALYTICS_TOKEN
    if CLIENT_ID and CLIENT_SECRET and REDIRECT_URI:
        kwargs.update(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri=REDIRECT_URI)
    if not kwargs:
        raise SystemExit("Set at least UPSTOX_ANALYTICS_TOKEN before running this script")

    broker = await create_broker("upstox", **kwargs)
    print("Broker created:", broker)

    instruments = await _step("instruments (no auth)", broker.instruments.fetch_instruments())
    if not instruments:
        return
    print("total:", len(instruments))
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE" and i.exchange == Exchange.NSE and i.segment == Segment.CASH
    )
    print("RELIANCE:", reliance)

    await _step(
        "historical (no auth)",
        broker.historical.get_candles(reliance, datetime.now() - timedelta(days=10), datetime.now(), 1440),
    )

    if hasattr(broker, "market"):
        await _step("market.get_quote", broker.market.get_quote(reliance))
        await _step("market.get_ltp", broker.market.get_ltp([reliance]))
        await _step("market.get_ohlc", broker.market.get_ohlc([reliance]))

    await _step("fundamentals.get_company_profile", broker.fundamentals.get_company_profile(reliance))
    await _step("fundamentals.get_balance_sheet", broker.fundamentals.get_balance_sheet(reliance))
    await _step("fundamentals.get_cash_flow", broker.fundamentals.get_cash_flow(reliance))
    await _step("fundamentals.get_income_statement", broker.fundamentals.get_income_statement(reliance))
    await _step("fundamentals.get_share_holdings", broker.fundamentals.get_share_holdings(reliance))
    await _step("fundamentals.get_key_ratios", broker.fundamentals.get_key_ratios(reliance))
    await _step("fundamentals.get_corporate_actions", broker.fundamentals.get_corporate_actions(reliance))
    await _step("fundamentals.get_competitors", broker.fundamentals.get_competitors(reliance))

    await _step("news.get_news", broker.news.get_news([reliance]))

    if hasattr(broker, "portfolio"):
        # Not skipped like orders — Groww/Fyers precedent is that reads
        # (unlike writes) usually work without static IP, so worth
        # actually trying rather than assuming it's blocked.
        await _step("portfolio.holdings", broker.portfolio.holdings())
        await _step("portfolio.positions", broker.portfolio.positions())

    print("\n--- streaming ---")
    got_tick = asyncio.Event()

    async def on_tick(tick):
        print("tick:", tick)
        got_tick.set()

    try:
        await broker.streaming.subscribe_ltp([reliance], on_tick)
        try:
            await asyncio.wait_for(got_tick.wait(), timeout=15)
        except asyncio.TimeoutError:
            print("no tick received in 15s (market may be closed)")
        await broker.streaming.unsubscribe_ltp([reliance])
    except Exception:
        print("FAILED: streaming")
        traceback.print_exc()

    await broker.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
