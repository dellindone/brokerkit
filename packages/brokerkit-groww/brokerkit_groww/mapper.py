from datetime import datetime
from decimal import Decimal
from typing import Any

from brokerkit.enums import (
    Exchange, OrderStatus, OrderType, Product, Segment, TransactionType, Validity,
)
from brokerkit.models.order import Order, OrderRequest
from brokerkit.models.portfolio import Holding
from brokerkit.models.position import Position

_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.PENDING,
    "ACKED": OrderStatus.PENDING,
    "APPROVED": OrderStatus.OPEN,
    "OPEN": OrderStatus.OPEN,
    "TRIGGER_PENDING": OrderStatus.OPEN,
    "MODIFICATION_REQUESTED": OrderStatus.OPEN,
    "CANCELLATION_REQUESTED": OrderStatus.OPEN,
    "EXECUTED": OrderStatus.EXECUTED,
    "COMPLETED": OrderStatus.EXECUTED,
    "DELIVERY_AWAITED": OrderStatus.EXECUTED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "FAILED": OrderStatus.FAILED,
}


def map_status(raw: str) -> OrderStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"Unknown Groww order status: {raw!r}") from None


def _decimal(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _dt(v: str | None) -> datetime | None:
    return None if v is None else datetime.fromisoformat(v)


def order_request_to_groww(request: OrderRequest) -> dict[str, Any]:
    """OrderRequest -> place_order kwargs."""
    payload: dict[str, Any] = {
        "trading_symbol": request.instrument.symbol,
        "exchange": request.instrument.exchange.value,
        "segment": request.instrument.segment.value,
        "transaction_type": request.transaction_type.value,
        "order_type": request.order_type.value,
        "product": request.product.value,
        "validity": request.validity.value,
        "quantity": request.quantity,
    }
    if request.price is not None:
        payload["price"] = float(request.price)
    if request.trigger_price is not None:
        payload["trigger_price"] = float(request.trigger_price)
    return payload


def groww_to_order(data: dict[str, Any]) -> Order:
    """get_order_detail / get_order_list item -> Order."""
    return Order(
        order_id=data["groww_order_id"],
        status=map_status(data["order_status"]),
        trading_symbol=data["trading_symbol"],
        exchange=Exchange(data["exchange"]),
        segment=Segment(data["segment"]),
        transaction_type=TransactionType(data["transaction_type"]),
        order_type=OrderType(data["order_type"]),
        product=Product(data["product"]),
        validity=Validity(data["validity"]),
        quantity=data["quantity"],
        filled_quantity=data.get("filled_quantity") or 0,
        price=_decimal(data.get("price")),
        trigger_price=_decimal(data.get("trigger_price")),
        average_price=_decimal(data.get("average_fill_price")),
        status_message=data.get("remark"),
        created_at=_dt(data.get("created_at")),
        updated_at=_dt(data.get("exchange_time")),
    )


def place_response_to_order(data: dict[str, Any], request: OrderRequest) -> Order:
    """place_order ka thin response + original request -> Order."""
    return Order(
        order_id=data["groww_order_id"],
        status=map_status(data["order_status"]),
        trading_symbol=request.instrument.symbol,
        exchange=request.instrument.exchange,
        segment=request.instrument.segment,
        transaction_type=request.transaction_type,
        order_type=request.order_type,
        product=request.product,
        validity=request.validity,
        quantity=request.quantity,
        price=request.price,
        trigger_price=request.trigger_price,
        status_message=data.get("remark"),
    )

def groww_to_holding(data: dict[str, Any]) -> Holding:
    return Holding(
        trading_symbol=data["trading_symbol"],
        isin=data.get("isin"),
        quantity=data["quantity"],
        average_price=_decimal(data["average_price"]) or Decimal("0"),
        pledged_quantity=data.get("pledge_quantity") or 0,
        t1_quantity=data.get("t1_quantity") or 0,
    )


def groww_to_position(data: dict[str, Any]) -> Position:
    # Groww: debit = buy side, credit = sell side
    return Position(
        trading_symbol=data["trading_symbol"],
        exchange=Exchange(data["exchange"]),
        segment=Segment(data["segment"]),
        product=Product(data["product"]),
        quantity=data["quantity"],
        buy_quantity=data.get("debit_quantity") or 0,
        buy_price=_decimal(data.get("debit_price")),
        sell_quantity=data.get("credit_quantity") or 0,
        sell_price=_decimal(data.get("credit_price")),
        realised_pnl=_decimal(data.get("realised_pnl")),
        isin=data.get("symbol_isin"),
    )
