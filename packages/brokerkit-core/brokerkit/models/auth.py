"""Authentication token model."""

from datetime import datetime, timedelta

from pydantic import BaseModel

from brokerkit.utils.datetime import IST

EXPIRY_SAFETY_BUFFER = timedelta(minutes=2)
"""Treat a token as expired slightly early, so a refresh cannot lose a race
against a call already in flight."""


class AuthToken(BaseModel):
    """An access token and when it stops being valid.

    Brokers differ sharply in how they express expiry, and assuming a fixed
    lifetime has broken this framework before: Groww and Zerodha expire at a
    fixed 6:00 AM IST, Angel One's JWT expires on a wall-clock boundary that
    depends on when you logged in (so its life ranges from most of a day to
    minutes), and Fyers and Upstox give no expiry signal at all. Adapters
    therefore compute ``expires_at`` from whatever their broker actually
    provides -- decoding the token when it is a JWT -- rather than adding a
    constant.
    """

    token: str
    """The access token string, passed to the broker on every call."""

    expires_at: datetime
    """When the token stops being valid. Timezone-aware, in IST."""

    @property
    def is_expired(self) -> bool:
        """Whether the token is expired, counting the safety buffer."""
        return datetime.now(IST) >= self.expires_at - EXPIRY_SAFETY_BUFFER
