"""BrokerKit basic example — Milestone 1 end-to-end.

Chalane ke liye:
    export GROWW_API_KEY=...      # Groww ka TOTP api key
    export GROWW_TOTP_SECRET=...  # TOTP secret
    python examples/basic/main.py
"""

import asyncio
import os

from brokerkit import BrokerKitError, Exchange, Segment, create_broker


async def main() -> None:
    broker = await create_broker(
        "groww",
        totp_key=os.environ["GROWW_API_KEY"],
        totp_secret=os.environ["GROWW_TOTP_SECRET"],
    )
    print(f"Connected: {broker.name}")

    # Instrument lookup (thin adapter: fetch + filter app-side)
    instruments = await broker.instruments.fetch_instruments()
    reliance = next(
        i for i in instruments
        if i.symbol == "RELIANCE"
        and i.exchange == Exchange.NSE
        and i.segment == Segment.CASH
    )
    print(f"Instrument: {reliance.name} isin={reliance.isin} token={reliance.exchange_token}")

    # Quote (Groww data subscription chahiye — na ho to skip)
    try:
        quote = await broker.market.get_quote(reliance)
        print(f"LTP: {quote.last_price}  OHLC: {quote.ohlc}")
    except BrokerKitError as e:
        print(f"Quote skip (data subscription?): {e}")

    # Holdings
    holdings = await broker.portfolio.holdings()
    print(f"Holdings ({len(holdings)}):")
    for h in holdings:
        print(f"  {h.trading_symbol}: {h.quantity} @ {h.average_price}")

    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
