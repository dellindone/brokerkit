import asyncio
from growwapi import GrowwAPI
from decimal import Decimal

from brokerkit.enums import OrderType, Segment
from brokerkit.exceptions.order import OrderError
from brokerkit.interfaces.order import OrderProvider
from brokerkit.models.order import Order, OrderRequest

from brokerkit_groww.errors import groww_errors
from brokerkit_groww.mapper import (
    groww_to_order,
    order_request_to_groww,
    place_response_to_order,
)

class GrowwOrderProvider(OrderProvider):
    def __init__(self, client: GrowwAPI):
        self._client = client

    async def place_order(self, request: OrderRequest) -> Order:
        payload = order_request_to_groww(request)
        with groww_errors(OrderError):
            resp = await asyncio.to_thread(self._client.place_order, **payload)
        return place_response_to_order(resp)

    async def modify(
            self, order_id: str, segment: Segment, *,
            quantity: int | None = None,
            order_type: OrderType | None = None,
            price: Decimal | None = None,
            trigger_price: Decimal | None = None,
        ) -> Order:
        current = await self.get_order(order_id, segment)
        kwargs: dict = {
            "groww_order_id": order_id,
            "segment": segment.value,
            "quantity": quantity if quantity is not None else current.quantity,
            "order_type": (order_type or current.order_type).value,
        }
        new_price = price if price is not None else current.price
        new_trigger = trigger_price if trigger_price is not None else current.trigger_price
        if new_price is not None:
            kwargs["price"] = float(new_price)
        if new_trigger is not None:
            kwargs["trigger_price"] = float(new_trigger)
        with groww_errors(OrderError):
            await asyncio.to_thread(self._client.modify_order, **kwargs)
        return await self.get_order(order_id, segment)
    
    async def cancel(self, order_id: str, segment: Segment) -> Order:
        with groww_errors(OrderError):
            await asyncio.to_thread(
                self._client.cancel_order,
                groww_order_id=order_id,
                segment=segment.value,
            )
        return await self.get_order(order_id, segment)
    
    async def get_order(self, order_id: str, segment: Segment) -> Order:
        with groww_errors(OrderError):
            data = await asyncio.to_thread(
                self._client.get_order_detail,
                segment=segment.value,
                groww_order_id=order_id,
            )
        return groww_to_order(data)

    async def list_orders(self) -> list[Order]:
        with groww_errors(OrderError):
            data = await asyncio.to_thread(self._client.get_order_list, 0, 25)
        return [groww_to_order(o) for o in data.get("order_list", [])]
    