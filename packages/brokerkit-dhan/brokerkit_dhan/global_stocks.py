"""Dhan Global Stocks (US equities) extra."""

import asyncio
import csv
import io
from decimal import Decimal
from typing import Any

import requests
from pydantic import BaseModel

from brokerkit.exceptions.order import OrderError

from brokerkit_dhan.errors import check

# Global Stocks is a genuinely separate world from the Indian core: prices
# are USD, quantities are FRACTIONAL (whole-share `int` won't do), and the
# exchange segment is INX_EQ (no core Exchange value). So it gets its own
# adapter-local models and provider, off the shared Broker base — same
# placement precedent as Upstox's fundamentals/news/market_information and
# its adapter-local MultiOrderResult.

_GLOBAL_CSV_URL = "https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv"


class GlobalInstrument(BaseModel):
    """A US-market instrument (Global Stocks). Adapter-local because core
    cannot represent fractional quantities, USD prices or US exchanges."""
    security_id: str          # SCRIP_CODE — the id every global order/quote call needs
    symbol: str               # ticker, e.g. "AAPL"
    name: str
    isin: str | None = None
    exchange: str             # real US exchange: NYSE / NASDAQ / CBOE / NYSE Arca
    fractional: bool = False
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("1")


class GlobalOrder(BaseModel):
    """A US-market order. Adapter-local; keeps the broker\'s own status
    vocabulary rather than mapping to core, as the lifecycle differs."""
    order_id: str
    status: str               # raw Dhan status (TRANSIT/PENDING/TRADED/...) — kept raw, no core OrderStatus mapping (different lifecycle)
    trading_symbol: str = ""
    security_id: str = ""
    transaction_type: str = ""
    order_type: str = ""
    quantity: Decimal | None = None      # fractional
    traded_quantity: Decimal | None = None
    price: Decimal | None = None         # USD
    average_price: Decimal | None = None
    error_message: str | None = None


class GlobalHolding(BaseModel):
    """A US-market holding."""
    trading_symbol: str
    security_id: str = ""
    quantity: Decimal
    average_price: Decimal                # USD
    last_price: Decimal | None = None
    current_value: Decimal | None = None
    gain_value: Decimal | None = None


class GlobalFundLimit(BaseModel):
    """Available funds and margin for US trading."""
    available_cash: Decimal | None = None
    settled_cash: Decimal | None = None
    unsettled_cash: Decimal | None = None
    margin_utilized: Decimal | None = None


class GlobalMarketStatus(BaseModel):
    """Whether the US market is currently open, with session times."""
    status: str | None = None             # open / closed
    market_open_time: str | None = None
    market_close_time: str | None = None
    holiday: bool | None = None


def _d(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


def _to_order(data: dict[str, Any]) -> GlobalOrder:
    return GlobalOrder(
        order_id=str(data.get("orderId") or ""),
        status=data.get("orderStatus") or "",
        trading_symbol=data.get("tradingSymbol") or data.get("displayName") or "",
        security_id=str(data.get("securityId") or ""),
        transaction_type=data.get("transactionType") or "",
        order_type=data.get("orderType") or "",
        quantity=_d(data.get("quantity")),
        traded_quantity=_d(data.get("tradedQty")),
        price=_d(data.get("price")),
        average_price=_d(data.get("avgTradedPrice")),
        error_message=data.get("omsErrorDescription") or None,
    )


def _to_holding(data: dict[str, Any]) -> GlobalHolding:
    return GlobalHolding(
        trading_symbol=data.get("tradingSymbol") or data.get("displayName") or "",
        security_id=str(data.get("securityId") or ""),
        quantity=_d(data.get("quantity")) or Decimal("0"),
        average_price=_d(data.get("avgCostPrice")) or Decimal("0"),
        last_price=_d(data.get("ltp")),
        current_value=_d(data.get("currentValue")),
        gain_value=_d(data.get("gainValue")),
    )


def _parse_global_instruments(text: str) -> list[GlobalInstrument]:
    out: list[GlobalInstrument] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(
                GlobalInstrument(
                    security_id=row["SCRIP_CODE"],
                    symbol=row.get("SYMBOL") or row.get("TRADING_SYMBOL") or "",
                    name=row.get("SYMBOL_NAME") or "",
                    isin=(row.get("ISIN_CODE") or None),
                    exchange=row.get("CUSTOM_EXCH") or row.get("EXCHANGE") or "",
                    fractional=(row.get("FRACTION") or "").strip().lower() == "true",
                    tick_size=_d(row.get("TICK_SIZE")) or Decimal("0.01"),
                    lot_size=_d(row.get("LOT_SIZE")) or Decimal("1"),
                )
            )
        except (ValueError, KeyError):
            continue
    return out


class DhanGlobalStocks:
    """`broker.global_stocks` — US equity trading. Instrument list is a
    public CSV (no auth); orders/holdings/funds/market-status need the same
    access token as the domestic side (INX_EQ order writes still require
    static IP, same as Indian order writes)."""

    def __init__(self, dhan):
        self._dhan = dhan

    async def fetch_instruments(self) -> list[GlobalInstrument]:
        def _fetch() -> str:
            r = requests.get(_GLOBAL_CSV_URL, timeout=60)
            r.raise_for_status()
            return r.text
        text = await asyncio.to_thread(_fetch)
        return await asyncio.to_thread(_parse_global_instruments, text)

    async def place_order(
        self,
        security_id: str,
        transaction_type: str,
        order_type: str,
        *,
        quantity: Decimal | float = 0,
        price: Decimal | float = 0,
        trigger_price: Decimal | float | None = None,
        stop_loss_price: Decimal | float | None = None,
        target_price: Decimal | float | None = None,
        amount: Decimal | float | None = None,
        after_market_order: bool = False,
        tag: str | None = None,
    ) -> GlobalOrder:
        resp = await asyncio.to_thread(
            self._dhan.place_global_order,
            security_id=security_id,
            transaction_type=transaction_type.upper(),
            order_type=order_type.upper(),
            quantity=float(quantity),
            price=float(price),
            trigger_price=None if trigger_price is None else float(trigger_price),
            stop_loss_price=None if stop_loss_price is None else float(stop_loss_price),
            target_price=None if target_price is None else float(target_price),
            amount=None if amount is None else float(amount),
            after_market_order=after_market_order,
            tag=tag,
        )
        data = check(resp, OrderError)
        return _to_order(data if isinstance(data, dict) else {"orderId": "", "orderStatus": ""})

    async def modify_order(
        self,
        order_id: str,
        order_type: str,
        transaction_type: str,
        security_id: str,
        *,
        quantity: Decimal | float | None = None,
        price: Decimal | float | None = None,
        leg_name: str | None = None,
    ) -> GlobalOrder:
        resp = await asyncio.to_thread(
            self._dhan.modify_global_order,
            order_id=order_id,
            order_type=order_type.upper(),
            transaction_type=transaction_type.upper(),
            security_id=security_id,
            quantity=None if quantity is None else float(quantity),
            price=None if price is None else float(price),
            leg_name=leg_name,
        )
        data = check(resp, OrderError)
        return await self.get_order(order_id)

    async def cancel_order(self, order_id: str) -> GlobalOrder:
        resp = await asyncio.to_thread(self._dhan.cancel_global_order, order_id)
        check(resp, OrderError)
        return await self.get_order(order_id)

    async def get_order(self, order_id: str) -> GlobalOrder:
        resp = await asyncio.to_thread(self._dhan.get_global_order_by_id, order_id)
        data = check(resp, OrderError)
        if isinstance(data, list):
            data = data[0] if data else {}
        return _to_order(data or {})

    async def list_orders(self) -> list[GlobalOrder]:
        resp = await asyncio.to_thread(self._dhan.get_global_order_list)
        data = check(resp, OrderError)
        return [_to_order(o) for o in (data or [])]

    async def holdings(self) -> list[GlobalHolding]:
        resp = await asyncio.to_thread(self._dhan.get_global_holdings)
        data = check(resp)
        return [_to_holding(h) for h in (data or [])]

    async def fund_limit(self) -> GlobalFundLimit:
        resp = await asyncio.to_thread(self._dhan.get_global_fund_limit)
        data = check(resp) or {}
        return GlobalFundLimit(
            available_cash=_d(data.get("availableCash")),
            settled_cash=_d(data.get("settledCash")),
            unsettled_cash=_d(data.get("unsettledCash")),
            margin_utilized=_d(data.get("marginUtilized")),
        )

    async def market_status(self) -> GlobalMarketStatus:
        resp = await asyncio.to_thread(self._dhan.get_global_market_status)
        data = check(resp) or {}
        return GlobalMarketStatus(
            status=data.get("status"),
            market_open_time=data.get("marketOpenTime"),
            market_close_time=data.get("marketCloseTime"),
            holiday=data.get("holidayFlag"),
        )
