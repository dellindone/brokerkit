import asyncio
from datetime import datetime
from decimal import Decimal

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_angelone.errors import angel_errors, check
from brokerkit_angelone.mapper import to_angel_exchange

# Angel's getCandleData `interval` enum -> the minute count each represents.
# No arbitrary minute count is accepted (unlike Dhan's raw-int intraday), so
# interval_minutes is mapped to the nearest supported bucket, or ONE_DAY for
# anything >= a day. Values verified against Angel's historical-API docs.
_INTERVALS = {
    1: "ONE_MINUTE",
    3: "THREE_MINUTE",
    5: "FIVE_MINUTE",
    10: "TEN_MINUTE",
    15: "FIFTEEN_MINUTE",
    30: "THIRTY_MINUTE",
    60: "ONE_HOUR",
}
_DAILY_THRESHOLD = 1440
# Angel dates are "YYYY-MM-DD HH:MM" (minute precision, IST implied).
_DATE_FMT = "%Y-%m-%d %H:%M"


def _interval(interval_minutes: int) -> str:
    if interval_minutes >= _DAILY_THRESHOLD:
        return "ONE_DAY"
    try:
        return _INTERVALS[interval_minutes]
    except KeyError:
        raise ValueError(
            f"Angel supports intervals {sorted(_INTERVALS)} min (or >= {_DAILY_THRESHOLD} "
            f"for daily); got {interval_minutes}"
        ) from None


class AngelHistoricalData(HistoricalDataProvider):
    def __init__(self, client):
        self._client = client  # shared SmartConnect

    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        params = {
            "exchange": to_angel_exchange(instrument),
            "symboltoken": instrument.exchange_token,
            "interval": _interval(interval_minutes),
            "fromdate": start.strftime(_DATE_FMT),
            "todate": end.strftime(_DATE_FMT),
        }
        with angel_errors():
            resp = await asyncio.to_thread(self._client.getCandleData, params)
        data = check(resp) or []
        return [_row_to_candle(r) for r in data]


def _row_to_candle(row: list) -> Candle:
    """Each row is [timestamp_iso, open, high, low, close, volume] — rupee
    floats (REST is not in paise, unlike the master/feed). Timestamp is ISO
    8601 with the IST offset, e.g. "2023-09-06T11:15:00+05:30"."""
    return Candle(
        timestamp=datetime.fromisoformat(row[0]),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=int(row[5]) if len(row) > 5 and row[5] is not None else 0,
    )
