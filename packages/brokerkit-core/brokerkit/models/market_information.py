"""Market-wide analytics models.

Derivatives analytics (open interest, max pain, put-call ratio), institutional
flows, ranked screeners and the market calendar, returned by
:class:`~brokerkit.interfaces.market_information.MarketInformationProvider`.

Not every broker exposes these; this is an optional capability rather than
part of the shared broker contract.
"""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel


class OiStrike(BaseModel):
    """Call and put open interest at one strike."""

    strike_price: Decimal
    call_oi: int
    put_oi: int


class OpenInterest(BaseModel):
    """Open-interest distribution across strikes for an expiry."""

    total_calls: int
    total_puts: int
    spot_closing_price: Decimal
    expiry: date
    strikes: list[OiStrike]


class ChangeInOiStrike(BaseModel):
    """Change in call and put open interest at one strike."""

    strike_price: Decimal
    call_change_oi: int
    put_change_oi: int


class ChangeInOpenInterest(BaseModel):
    """Change in open interest across strikes for an expiry."""

    total_call_change_oi: int
    total_put_change_oi: int
    spot_closing_price: Decimal
    expiry: date
    strikes: list[ChangeInOiStrike]


class MaxPainInsight(BaseModel):
    """Max-pain reading at one point in the session."""

    max_pain: Decimal
    spot_price: Decimal
    time: time


class MaxPain(BaseModel):
    """Max-pain level for an expiry: the strike where option buyers lose most."""

    instrument_key: str
    expiry_date: date
    max_pain: Decimal
    spot_closing_price: Decimal
    insights: list[MaxPainInsight]


class PcrInsight(BaseModel):
    """Put-call ratio reading at one point in the session."""

    pcr: float
    spot_price: Decimal
    time: time


class Pcr(BaseModel):
    """Put-call ratio for an expiry, a common sentiment gauge."""

    instrument_key: str
    expiry_date: date
    pcr: float
    spot_closing_price: Decimal
    insights: list[PcrInsight]


class InstitutionalActivity(BaseModel):
    """Institutional buying and selling for one period."""

    time_stamp: datetime
    buy_amount: Decimal
    sell_amount: Decimal
    buy_contracts: int = 0
    sell_contracts: int = 0
    oi_contracts: int = 0
    oi_amount: Decimal = Decimal("0")
    total_long_contracts: int = 0
    total_short_contracts: int = 0
    total_call_long_contracts: int = 0
    total_put_long_contracts: int = 0
    total_call_short_contracts: int = 0
    total_put_short_contracts: int = 0


class SmartlistPriceChange(BaseModel):
    """Price and its change for a smartlist entry."""

    current: Decimal
    close_price: Decimal
    change_abs: Decimal
    change_pct: float


class SmartlistMetric(BaseModel):
    """One ranked metric on a smartlist entry."""

    current: Decimal
    previous: Decimal
    change_abs: Decimal
    change_pct: float


class SmartlistEntry(BaseModel):
    """A single instrument's row in a ranked screener."""

    instrument_key: str
    price: SmartlistPriceChange
    metric: SmartlistMetric


class Smartlist(BaseModel):
    """A ranked screener of futures or options instruments."""

    asset_type: str
    category: str
    time_stamp: datetime
    metric_key: str
    entries: list[SmartlistEntry]
    page_number: int
    page_size: int
    total_pages: int


class MtfPrice(BaseModel):
    """Price detail for a margin-trading-facility entry."""

    actual_price: Decimal
    mtf_price: Decimal
    margin_saved: Decimal
    close_price: Decimal


class MtfSmartlistEntry(BaseModel):
    """A single instrument's row in the MTF screener."""

    instrument_key: str
    price: MtfPrice
    mtf_percent: float


class MtfSmartlist(BaseModel):
    """A ranked screener of margin-trading-facility instruments."""

    asset_type: str
    category: str
    time_stamp: datetime
    metric_key: str
    entries: list[MtfSmartlistEntry]
    page_number: int
    page_size: int
    total_pages: int


class ExchangeTiming(BaseModel):
    """Session open and close times for one exchange segment."""

    exchange: str
    start_time: datetime
    end_time: datetime


class MarketHoliday(BaseModel):
    """A market holiday, and which exchanges observe it."""

    date: date
    description: str
    holiday_type: str
    closed_exchanges: list[str]
    open_exchanges: list[ExchangeTiming]


class MarketStatus(BaseModel):
    """Current open or closed status of an exchange segment."""

    exchange: str
    status: str
    last_updated: datetime
