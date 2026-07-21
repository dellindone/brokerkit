import asyncio
from datetime import datetime

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors

# Kite's fixed interval vocabulary (strings, not minute counts). Anything not
# in this map is rejected rather than silently rounded to a neighbour — the
# same policy as the Angel adapter's interval handling.
_INTERVALS = {
    1: "minute",
    3: "3minute",
    5: "5minute",
    10: "10minute",
    15: "15minute",
    30: "30minute",
    60: "60minute",
    24 * 60: "day",
}


class ZerodhaHistoricalData(HistoricalDataProvider):
    """Historical candles via `/instruments/historical/{token}/{interval}`.

    **Requires the paid ₹500/mo Kite Connect plan** — the free Personal plan
    has no historical data at all. Same account-state wall as the market
    provider.

    Note this endpoint takes Kite's internal `instrument_token`, not the
    exchange token that core `Instrument.exchange_token` holds — see
    `mapper.instrument_token`, which reconstructs it from the exchange token
    using a relationship verified across the entire real master.
    """

    def __init__(self, client):
        self._client = client  # shared KiteConnect

    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        try:
            interval = _INTERVALS[interval_minutes]
        except KeyError:
            raise ValueError(
                f"Kite supports only {sorted(_INTERVALS)} minute intervals, "
                f"got {interval_minutes}"
            ) from None

        # Kite caps how much history one call may span per interval (e.g. 60
        # days for 1-minute candles); a longer range comes back as an
        # InputException rather than being silently truncated. Not chunked
        # here — the caller sees the broker's own error, matching how every
        # other adapter passes the range straight through.
        with zerodha_errors():
            rows = await asyncio.to_thread(
                self._client.historical_data,
                mapper.instrument_token(instrument),
                start,
                end,
                interval,
            )
        return [mapper.kite_to_candle(row) for row in rows or []]
