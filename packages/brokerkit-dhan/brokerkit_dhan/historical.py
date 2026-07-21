"""Dhan historical-data provider."""

import asyncio
from datetime import datetime
from decimal import Decimal

from brokerkit.interfaces.historical import HistoricalDataProvider
from brokerkit.models.candle import Candle
from brokerkit.models.instrument import Instrument

from brokerkit_dhan.errors import check
from brokerkit_dhan.mapper import _decimal, dhan_instrument_type, dhan_segment

# Dhan intraday supports 1/5/15/30/60 min (docs). Anything >= 1440 (a day)
# routes to the daily endpoint, same convention as the Fyers adapter.
_DAILY_THRESHOLD = 1440


def _columns_to_candles(body: dict) -> list[Candle]:
    """Dhan historical responses are columnar: parallel arrays
    open/high/low/close/volume/timestamp (epoch seconds). Zip into Candles."""
    opens = body.get("open") or []
    highs = body.get("high") or []
    lows = body.get("low") or []
    closes = body.get("close") or []
    volumes = body.get("volume") or []
    timestamps = body.get("timestamp") or []
    z = Decimal("0")
    out: list[Candle] = []
    for i in range(len(timestamps)):
        out.append(
            Candle(
                timestamp=datetime.fromtimestamp(int(timestamps[i])),
                open=_decimal(opens[i]) if i < len(opens) else z,
                high=_decimal(highs[i]) if i < len(highs) else z,
                low=_decimal(lows[i]) if i < len(lows) else z,
                close=_decimal(closes[i]) if i < len(closes) else z,
                volume=int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0,
            )
        )
    return out


class DhanHistoricalData(HistoricalDataProvider):
    """Dhan historical-data provider. See
    :class:`~brokerkit.interfaces.historical.HistoricalDataProvider`."""
    def __init__(self, dhan):
        self._dhan = dhan

    async def get_candles(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
        interval_minutes: int,
    ) -> list[Candle]:
        security_id = instrument.exchange_token
        segment = dhan_segment(instrument)
        instrument_type = dhan_instrument_type(instrument)
        from_date = start.date().isoformat()
        to_date = end.date().isoformat()

        if interval_minutes >= _DAILY_THRESHOLD:
            resp = await asyncio.to_thread(
                self._dhan.historical_daily_data,
                security_id=security_id,
                exchange_segment=segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
            )
        else:
            resp = await asyncio.to_thread(
                self._dhan.intraday_minute_data,
                security_id=security_id,
                exchange_segment=segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=interval_minutes,
            )
        body = check(resp) or {}
        return _columns_to_candles(body)

    async def get_expired_options(
        self,
        underlying: Instrument,
        expiry_flag: str,
        expiry_code: int,
        strike: str,
        option_type: str,
        from_date: str,
        to_date: str,
        required_data: list[str] | None = None,
        interval: int = 1,
    ) -> dict:
        """Dhan-exclusive extra (not on the shared ABC — no cross-broker
        equivalent, same placement precedent as Upstox's place_multi_order):
        rolling expired-options contract data for backtesting, up to 5 years
        back, strike-relative-to-spot (ATM / ATM+N / ATM-N). Returns the raw
        columnar payload ({ce: {...arrays...}, pe: {...}}) — a backtester
        wants the arrays (with iv/oi/spot alongside OHLC) directly, and
        Candle can't hold iv/oi/spot anyway.

        `expiry_flag`: "WEEK"/"MONTH". `expiry_code`: 1=near/2=next/3=far.
        `strike`: "ATM"/"ATM+10"/"ATM-10". `option_type`: "CALL"/"PUT".
        `interval`: 1/5/15/25/60 (note: this endpoint uses 25, not 30).
        """
        instrument_type = dhan_instrument_type(underlying)
        # rolling-options only accepts OPTIDX/OPTSTK
        if instrument_type not in ("OPTIDX", "OPTSTK"):
            instrument_type = "OPTIDX" if (underlying.underlying or underlying.symbol).upper() in {
                "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"
            } else "OPTSTK"
        resp = await asyncio.to_thread(
            self._dhan.expired_options_data,
            security_id=underlying.exchange_token,
            exchange_segment=dhan_segment(underlying),
            instrument_type=instrument_type,
            expiry_flag=expiry_flag,
            expiry_code=expiry_code,
            strike=strike,
            drv_option_type=option_type,
            required_data=required_data or ["open", "high", "low", "close", "volume", "oi", "iv", "spot"],
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )
        return check(resp) or {}
