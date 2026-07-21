import asyncio
from decimal import Decimal
from typing import Any

from brokerkit.enums import Product, TransactionType
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.charges import ChargesProvider
from brokerkit.models.charges import BrokerageCharges, BrokerageTaxes, OtherCharges
from brokerkit.models.instrument import Instrument

from brokerkit_zerodha import mapper
from brokerkit_zerodha.errors import zerodha_errors


class ZerodhaCharges(ChargesProvider):
    """Pre-trade cost estimate via Kite's "virtual contract note"
    (`POST /charges/orders`). Same placement call as the Upstox and Angel
    charges providers — implements the core `ChargesProvider` ABC but hangs
    off the shared `Broker` base as a Zerodha-only extra (`broker.charges`).

    Kite's endpoint takes a *list* of hypothetical orders and returns one
    entry per order, so the single-order core signature maps onto a
    one-element list and the first result is read back.

    Response shape below is doc-derived and NOT yet live-verified — the
    Angel adapter's equivalent silently produced zeros for three fields
    because the real labels differed from every plausible guess, so this
    parser is one of the first things the raw-dump script checks. Unlike
    Angel's nested `breakup` tree, Kite's charges object is documented as
    flat with a nested `gst` sub-object.
    """

    def __init__(self, client):
        self._client = client  # shared KiteConnect

    async def get_brokerage(
        self,
        instrument: Instrument,
        quantity: int,
        product: Product,
        transaction_type: TransactionType,
        price: Decimal,
    ) -> BrokerageCharges:
        params = [
            {
                # order_id is required by the endpoint but is only an echo
                # field for a hypothetical order — Kite's own docs use a
                # placeholder here too.
                "order_id": "brokerkit",
                "exchange": mapper.to_kite_exchange(instrument),
                "tradingsymbol": instrument.symbol,
                "transaction_type": transaction_type.value,
                "variety": mapper.VARIETY_REGULAR,
                "product": mapper.product_to_kite(product),
                "order_type": "MARKET",
                "quantity": quantity,
                "average_price": float(price),
            }
        ]
        with zerodha_errors():
            raw = await asyncio.to_thread(
                self._client.get_virtual_contract_note, params
            )
        if not raw:
            raise BrokerKitError(f"Kite returned no contract note: {raw!r}")
        return _to_brokerage_charges(raw[0])


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return Decimal("0")


def _to_brokerage_charges(entry: dict[str, Any]) -> BrokerageCharges:
    charges = entry.get("charges") or {}
    gst = charges.get("gst") or {}

    # `transaction_tax` is Kite's generic field for the security-transaction
    # tax; `transaction_tax_type` names which one it is ("stt" for equity/FnO,
    # "ctt" for commodities). Both map onto core's single `stt` field.
    return BrokerageCharges(
        total=_dec(charges.get("total")),
        brokerage=_dec(charges.get("brokerage")),
        taxes=BrokerageTaxes(
            gst=_dec(gst.get("total")),
            stt=_dec(charges.get("transaction_tax")),
            stamp_duty=_dec(charges.get("stamp_duty")),
        ),
        other_charges=OtherCharges(
            transaction=_dec(charges.get("exchange_turnover_charge")),
            # Kite folds clearing into the exchange turnover charge and does
            # not itemize it separately -> 0, same as the Angel adapter.
            clearing=Decimal("0"),
            sebi_turnover=_dec(charges.get("sebi_turnover_charge")),
        ),
        # Kite's contract note has no DP-plan structure (DP charges are
        # levied separately on delivery sells and aren't part of this
        # response) — same gap as Angel's.
        dp_plan=None,
    )
