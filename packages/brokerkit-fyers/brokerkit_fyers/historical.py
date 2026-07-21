"""Fyers historical-data provider."""

import asyncio
from datetime import datetime

from fyers_apiv3.fyersModel import FyersModel

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_fyers.errors import check
from brokerkit_fyers.mapper import fyers_symbol, fyers_to_candle


class FyersHistorical(HistoricalDataProvider):
    """Second half of the reason this adapter exists — same scrutiny level as market.py."""

    def __init__(self, client: FyersModel) -> None:
        self._client = client

    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        # "D" for daily-or-coarser, else the raw minute count as a string.
        # Verified against the *official sample code* (which literally uses
        # "D"), not the docstring (which claims "Day"/"1D" — trusting the
        # working sample over a possibly-stale docstring).
        resolution = "D" if interval_minutes >= 1440 else str(interval_minutes)
        data = {
            "symbol": fyers_symbol(instrument),
            "resolution": resolution,
            "date_format": "0",  # epoch seconds — avoids yyyy-mm-dd timezone ambiguity
            "range_from": str(int(start.timestamp())),
            "range_to": str(int(end.timestamp())),
            "cont_flag": "0",
        }
        resp = await asyncio.to_thread(self._client.history, data=data)
        check(resp)
        return [fyers_to_candle(row) for row in resp.get("candles") or []]
