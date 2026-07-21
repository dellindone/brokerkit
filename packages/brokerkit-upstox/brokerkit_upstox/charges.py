import asyncio
from decimal import Decimal
from typing import Any

from upstox_client import ApiClient, ChargeApi, Configuration

from brokerkit.enums import Product, TransactionType
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.charges import ChargesProvider
from brokerkit.models.charges import BrokerageCharges, BrokerageTaxes, DepositoryPlan, OtherCharges
from brokerkit.models.instrument import Instrument

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import _PRODUCT_TO_UPSTOX, upstox_key

_API_VERSION = "2.0"


def _brokerage_to_model(data: dict[str, Any]) -> BrokerageCharges:
    dp_plan = data.get("dp_plan")
    return BrokerageCharges(
        total=Decimal(str(data["total"])),
        brokerage=Decimal(str(data["brokerage"])),
        taxes=BrokerageTaxes(
            gst=Decimal(str(data["taxes"]["gst"])),
            stt=Decimal(str(data["taxes"]["stt"])),
            stamp_duty=Decimal(str(data["taxes"]["stamp_duty"])),
        ),
        other_charges=OtherCharges(
            transaction=Decimal(str(data["other_taxes"]["transaction"])),
            clearing=Decimal(str(data["other_taxes"]["clearing"])),
            sebi_turnover=Decimal(str(data["other_taxes"]["sebi_turnover"])),
        ),
        dp_plan=DepositoryPlan(name=dp_plan["name"], min_expense=Decimal(str(dp_plan["min_expense"])))
        if dp_plan else None,
    )


class UpstoxCharges(ChargesProvider):
    """Works with either token type (Analytics Token covers "Charges" per
    Upstox's docs — no OAuth/static-IP needed for this file), unlike
    orders/portfolio.
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._client = ChargeApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_brokerage(
        self,
        instrument: Instrument,
        quantity: int,
        product: Product,
        transaction_type: TransactionType,
        price: Decimal,
    ) -> BrokerageCharges:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(
                self._client.get_brokerage,
                upstox_key(instrument),
                quantity,
                _PRODUCT_TO_UPSTOX[product],
                transaction_type.value,
                float(price),
                _API_VERSION,
            )
        return _brokerage_to_model(resp.to_dict()["data"]["charges"])
