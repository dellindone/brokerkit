from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel


class OiStrike(BaseModel):
    strike_price: Decimal
    call_oi: int
    put_oi: int


class OpenInterest(BaseModel):
    total_calls: int
    total_puts: int
    spot_closing_price: Decimal
    expiry: date
    strikes: list[OiStrike]


class ChangeInOiStrike(BaseModel):
    strike_price: Decimal
    call_change_oi: int
    put_change_oi: int


class ChangeInOpenInterest(BaseModel):
    total_call_change_oi: int
    total_put_change_oi: int
    spot_closing_price: Decimal
    expiry: date
    strikes: list[ChangeInOiStrike]


class MaxPainInsight(BaseModel):
    max_pain: Decimal
    spot_price: Decimal
    time: time


class MaxPain(BaseModel):
    instrument_key: str
    expiry_date: date
    max_pain: Decimal
    spot_closing_price: Decimal
    insights: list[MaxPainInsight]


class PcrInsight(BaseModel):
    pcr: float
    spot_price: Decimal
    time: time


class Pcr(BaseModel):
    instrument_key: str
    expiry_date: date
    pcr: float
    spot_closing_price: Decimal
    insights: list[PcrInsight]


class InstitutionalActivity(BaseModel):
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
    current: Decimal
    close_price: Decimal
    change_abs: Decimal
    change_pct: float


class SmartlistMetric(BaseModel):
    current: Decimal
    previous: Decimal
    change_abs: Decimal
    change_pct: float


class SmartlistEntry(BaseModel):
    instrument_key: str
    price: SmartlistPriceChange
    metric: SmartlistMetric


class Smartlist(BaseModel):
    asset_type: str
    category: str
    time_stamp: datetime
    metric_key: str
    entries: list[SmartlistEntry]
    page_number: int
    page_size: int
    total_pages: int


class MtfPrice(BaseModel):
    actual_price: Decimal
    mtf_price: Decimal
    margin_saved: Decimal
    close_price: Decimal


class MtfSmartlistEntry(BaseModel):
    instrument_key: str
    price: MtfPrice
    mtf_percent: float


class MtfSmartlist(BaseModel):
    asset_type: str
    category: str
    time_stamp: datetime
    metric_key: str
    entries: list[MtfSmartlistEntry]
    page_number: int
    page_size: int
    total_pages: int


class ExchangeTiming(BaseModel):
    exchange: str
    start_time: datetime
    end_time: datetime


class MarketHoliday(BaseModel):
    date: date
    description: str
    holiday_type: str
    closed_exchanges: list[str]
    open_exchanges: list[ExchangeTiming]


class MarketStatus(BaseModel):
    exchange: str
    status: str
    last_updated: datetime
