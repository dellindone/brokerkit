"""Angel One charges provider."""

import asyncio
from decimal import Decimal
from typing import Any

from brokerkit.enums import Product, TransactionType
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.charges import ChargesProvider
from brokerkit.models.charges import BrokerageCharges, BrokerageTaxes, OtherCharges
from brokerkit.models.instrument import Instrument

from brokerkit_angelone.errors import angel_errors, check
from brokerkit_angelone.mapper import _PRODUCT_TO_ANGEL, to_angel_exchange


class AngelCharges(ChargesProvider):
    """Pre-trade cost estimate via Angel's `estimateCharges` endpoint. Same
    placement call as Upstox's charges provider — implements the core
    `ChargesProvider` ABC but lives off the shared `Broker` base as an
    Angel-only extra (`broker.charges`).

    Angel's endpoint takes a *list* of orders and returns a nested breakup;
    this maps the single-order core signature onto a one-element list and
    flattens the breakup by charge name. The exact nesting is doc-derived
    (auth-gated, so not live-verified) — the flatten walks the tree by
    {name, amount} shape so it tolerates depth differences; unmatched line
    items default to 0.
    """

    def __init__(self, client):
        self._client = client  # shared SmartConnect

    async def get_brokerage(
        self,
        instrument: Instrument,
        quantity: int,
        product: Product,
        transaction_type: TransactionType,
        price: Decimal,
    ) -> BrokerageCharges:
        params = {
            "orders": [
                {
                    "product_type": _PRODUCT_TO_ANGEL[product],
                    "transaction_type": transaction_type.value,
                    "quantity": str(quantity),
                    "price": str(price),
                    "exchange": to_angel_exchange(instrument),
                    "symbol_name": instrument.exchange_token or "",
                    "token": instrument.exchange_token or "",
                }
            ]
        }
        with angel_errors():
            resp = await asyncio.to_thread(self._client.estimateCharges, params)
        data = check(resp) or {}
        return _to_brokerage_charges(data)


def _flatten_charges(node: Any, out: dict[str, Decimal]) -> None:
    """Recursively collect every {name, amount, breakup?} leaf into a
    name -> amount map (lowercased names). Angel nests taxes under a parent
    `breakup` list whose own children are the individual charges."""
    if isinstance(node, dict):
        name = node.get("name")
        amount = node.get("amount")
        if isinstance(name, str) and amount is not None:
            try:
                out[name.strip().lower()] = Decimal(str(amount))
            except (ArithmeticError, ValueError):
                pass
        for value in node.values():
            _flatten_charges(value, out)
    elif isinstance(node, list):
        for item in node:
            _flatten_charges(item, out)


def _pick(flat: dict[str, Decimal], *names: str) -> Decimal:
    for n in names:
        if n in flat:
            return flat[n]
    return Decimal("0")


def _to_brokerage_charges(data: dict[str, Any]) -> BrokerageCharges:
    summary = data.get("summary") or data
    total = summary.get("total_charges")
    if total is None:
        total = summary.get("totalCharges")
    try:
        total_dec = Decimal(str(total)) if total is not None else Decimal("0")
    except (ArithmeticError, ValueError):
        raise BrokerKitError(f"Could not parse estimateCharges total: {total!r}") from None

    flat: dict[str, Decimal] = {}
    _flatten_charges(data, flat)

    # Names below are the REAL ones from a live response (2026-07-21), not
    # guesses — three of the initial guesses silently resolved to 0 because
    # Angel's labels differ from every plausible short form: it's "Angel One
    # Brokerage" (brand-prefixed), "Security Transaction Tax" (singular
    # "Security", not the usual "Securities"), and "SEBI Fees" (not "SEBI
    # Charges"/"turnover"). Fallback spellings are kept after each real name in
    # case Angel varies them per segment.
    #
    # Live shape: data.summary.total_charges + a two-level `breakup` tree —
    # ["Angel One Brokerage", "External Charges" -> [Exchange Transaction
    # Charges, Stamp Duty, IPFT charges, SEBI Fees], "Taxes" -> [Security
    # Transaction Tax, GST]]. The parent aggregates are flattened too but
    # simply never picked. "IPFT charges" has no core OtherCharges field, so
    # it is currently dropped (it was 0.0 on the verified equity-delivery
    # response) — same gap the Upstox adapter has with its own ipft.
    return BrokerageCharges(
        total=total_dec,
        brokerage=_pick(flat, "angel one brokerage", "brokerage"),
        taxes=BrokerageTaxes(
            gst=_pick(flat, "gst", "gst charges"),
            stt=_pick(flat, "security transaction tax", "securities transaction tax", "stt"),
            stamp_duty=_pick(flat, "stamp duty", "stamp charges"),
        ),
        other_charges=OtherCharges(
            transaction=_pick(flat, "exchange transaction charges", "transaction charges"),
            clearing=_pick(flat, "clearing charges"),  # Angel doesn't itemize this -> 0
            sebi_turnover=_pick(flat, "sebi fees", "sebi charges", "sebi turnover charges"),
        ),
        dp_plan=None,  # Angel's estimateCharges has no DP-plan structure
    )
