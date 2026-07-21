"""Option chain models."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import InstrumentType


class OptionGreeks(BaseModel):
    """Option sensitivities for a single contract.

    Availability varies a lot: some brokers return greeks inline with the
    chain, one exposes them through a separate endpoint that adapters merge
    in, and others have no greeks endpoint at all -- for those,
    :attr:`OptionContract.greeks` is always ``None``, which is a real
    capability gap rather than a mapping bug.

    All-zero greeks are not automatically wrong. Options on their expiry day
    legitimately return zeros once they are worthless, so sanity-check
    against a later expiry before assuming a bug.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float
    """Implied volatility."""

    rho: float | None = None
    """``None`` on brokers that omit it."""


class OptionContract(BaseModel):
    """One call or put at a single strike."""

    symbol: str
    strike: Decimal
    option_type: InstrumentType
    """:attr:`~brokerkit.enums.instrument_type.InstrumentType.CE` or
    :attr:`~brokerkit.enums.instrument_type.InstrumentType.PE`."""

    ltp: Decimal
    open_interest: int = 0
    volume: int = 0

    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    """Best bid and ask. Worth checking before trading options: a wide spread
    means poor execution regardless of how good the last price looks."""

    greeks: OptionGreeks | None = None
    """``None`` where the broker provides no greeks."""


class OptionChainStrike(BaseModel):
    """The call and put at one strike price.

    Either side may be ``None`` if the broker did not return it.
    """

    strike: Decimal
    call: OptionContract | None = None
    put: OptionContract | None = None


class OptionChain(BaseModel):
    """An option chain for one underlying at one expiry.

    Some brokers serve this from a single endpoint. Others have none at all,
    and their adapters assemble it by filtering the instrument master for the
    underlying's contracts, trimming to the strikes nearest spot, and quoting
    them in one batched call.
    """

    underlying_symbol: str
    underlying_ltp: Decimal
    """Spot price of the underlying, which the strikes are centred on."""

    expiry: date
    strikes: list[OptionChainStrike]
    """Ascending by strike price."""
