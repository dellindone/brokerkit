"""Open position model."""

from decimal import Decimal

from pydantic import BaseModel

from brokerkit.enums import Exchange, Product, Segment


class Position(BaseModel):
    """An open position for the current trading day.

    Covers intraday equity and derivatives exposure, as opposed to
    :class:`~brokerkit.models.portfolio.Holding`, which is settled stock in
    the demat account.
    """

    trading_symbol: str
    exchange: Exchange
    segment: Segment

    product: Product
    """Holding type, which decides how the position is margined."""

    quantity: int
    """Net quantity: positive is long, negative is short, zero means the
    position was opened and closed today."""

    buy_quantity: int = 0
    buy_price: Decimal | None = None
    """Average buy price, ``None`` if nothing was bought."""

    sell_quantity: int = 0
    sell_price: Decimal | None = None
    """Average sell price, ``None`` if nothing was sold."""

    realised_pnl: Decimal | None = None
    """Booked profit or loss on the closed part of the position."""

    isin: str | None = None
    """ISIN, where the broker's positions response carries one. Several do
    not, so this is often ``None`` even for equities."""
