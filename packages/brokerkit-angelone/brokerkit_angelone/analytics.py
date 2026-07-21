"""Angel One analytics extras."""

import asyncio
from datetime import date
from typing import Any

from brokerkit_angelone.errors import angel_errors, check

# Angel's market-data analytics endpoints (SmartConnect.optionGreek /
# gainersLosers / putCallRatio / oIBuildup / nseIntraday / bseIntraday).
# These have no Groww/Fyers/Dhan equivalent and don't fit Upstox's
# MarketInformationProvider ABC 1:1 (different endpoints/shapes), so — same
# call as Dhan's global_stocks/risk_control — this is an adapter-local
# provider (`broker.analytics`), not a core interface.
#
# Each method returns Angel's unwrapped `data` payload (list/dict) as-is:
# these are auth-gated so their exact response shapes aren't live-verified,
# and typing them from docs alone risks silently-wrong parsing — returning
# the raw payload is the honest choice (same precedent as Dhan's
# place_multi_order returning its raw, undocumented response). The documented
# request-param vocabularies are captured in each docstring.


class AngelAnalytics:
    """Angel One-specific market analytics. Adapter-local: the shapes are the
    broker\'s raw payloads, since they are not part of the shared contract."""
    def __init__(self, client):
        self._client = client  # shared SmartConnect

    async def option_greek(self, name: str, expiry: date) -> Any:
        """Greeks for every strike of `name` at `expiry`. `name` is the
        underlying (e.g. "NIFTY"); expiry is sent as Angel's "DDMMMYYYY".
        Returns a list of per-strike {strikePrice, optionType, delta, gamma,
        theta, vega, impliedVolatility, tradeVolume} nodes."""
        params = {"name": name, "expirydate": expiry.strftime("%d%b%Y").upper()}
        with angel_errors():
            resp = await asyncio.to_thread(self._client.optionGreek, params)
        return check(resp)

    async def gainers_losers(self, datatype: str, expirytype: str) -> Any:
        """Top F&O gainers/losers. `datatype` ∈ {"PercPriceGainers",
        "PercPriceLosers", "PercOIGainers", "PercOILosers"}; `expirytype` ∈
        {"NEAR", "NEXT", "FAR"}."""
        params = {"datatype": datatype, "expirytype": expirytype}
        with angel_errors():
            resp = await asyncio.to_thread(self._client.gainersLosers, params)
        return check(resp)

    async def oi_buildup(self, expirytype: str, datatype: str) -> Any:
        """OI build-up screener. `datatype` ∈ {"Long Built Up",
        "Short Built Up", "Short Covering", "Long Unwinding"}; `expirytype` ∈
        {"NEAR", "NEXT", "FAR"}."""
        params = {"expirytype": expirytype, "datatype": datatype}
        with angel_errors():
            resp = await asyncio.to_thread(self._client.oIBuildup, params)
        return check(resp)

    async def put_call_ratio(self) -> Any:
        """PCR per underlying (no params — GET)."""
        with angel_errors():
            resp = await asyncio.to_thread(self._client.putCallRatio)
        return check(resp)

    async def nse_intraday(self) -> Any:
        """NSE top intraday movers/smartlist (no params — GET)."""
        with angel_errors():
            resp = await asyncio.to_thread(self._client.nseIntraday)
        return check(resp)

    async def bse_intraday(self) -> Any:
        """BSE top intraday movers/smartlist (no params — GET)."""
        with angel_errors():
            resp = await asyncio.to_thread(self._client.bseIntraday)
        return check(resp)
