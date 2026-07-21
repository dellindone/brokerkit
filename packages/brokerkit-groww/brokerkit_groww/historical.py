"""Groww historical-data provider."""

import asyncio
from datetime import datetime

from growwapi import GrowwAPI

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_groww.errors import groww_errors
from brokerkit_groww.mapper import groww_to_candle

_FMT = "%Y-%m-%d %H:%M:%S"


class GrowwHistorical(HistoricalDataProvider):
    """Groww historical-data provider. See
    :class:`~brokerkit.interfaces.historical.HistoricalDataProvider`."""

    def __init__(self, client: GrowwAPI) -> None:
        self._client = client

    async def get_candles(
            self,
            instrument: Instrument,
            start: datetime,
            end: datetime,
            interval_minutes: int,
        ) -> list[Candle]:
        with groww_errors():
            data = await asyncio.to_thread(
                self._client.get_historical_candle_data,
                trading_symbol=instrument.symbol,
                exchange=instrument.exchange.value,
                segment=instrument.segment.value,
                start_time=start.strftime(_FMT),
                end_time=end.strftime(_FMT),
                interval_in_minutes=interval_minutes,
            )
        return [groww_to_candle(row) for row in (data or {}).get("candles") or []]
