import asyncio
from datetime import datetime

from upstox_client import ApiClient, Configuration, HistoryV3Api

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import upstox_key, upstox_to_candle


def _to_unit_interval(interval_minutes: int) -> tuple[str, int]:
    """core's single interval_minutes int -> Upstox's (unit, interval) pair.
    Upstox's V3 endpoint takes arbitrary integers within minutes/hours/days
    (verified live examples: minutes/1, minutes/3, minutes/15, hours/1) —
    weeks/months deliberately unsupported here (YAGNI, no caller needs them
    yet); an interval that isn't a whole number of hours/days below the
    1-day mark has no clean Upstox equivalent and raises rather than
    silently rounding.
    """
    if interval_minutes < 60:
        return "minutes", interval_minutes
    if interval_minutes == 1440:
        return "days", 1
    if interval_minutes % 60 == 0:
        return "hours", interval_minutes // 60
    raise ValueError(f"Unsupported interval_minutes for Upstox: {interval_minutes}")


class UpstoxHistorical(HistoricalDataProvider):
    """Second half of the reason this adapter exists, alongside market.py.
    No auth needed at all — verified from source: every method in
    history_v3_api.py sets `auth_settings = []`, meaning Upstox's
    historical-candle endpoints are genuinely public (unlike Market Quote,
    which needs a token even via the Analytics Token's no-auth-dance path).
    """

    def __init__(self, configuration: Configuration):
        self._client = HistoryV3Api(ApiClient(configuration))

    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        unit, interval = _to_unit_interval(interval_minutes)
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._client.get_historical_candle_data1,
                upstox_key(instrument),
                unit,
                interval,
                end.date().isoformat(),
                start.date().isoformat(),
            )
        candles = resp.data.candles if resp.data else []
        return [upstox_to_candle(row) for row in candles]
