import asyncio
from datetime import datetime, timedelta

import pyotp
from dhanhq.auth import DhanLogin

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import IST

# generateAccessToken's docs don't state a validity duration explicitly,
# but every other Dhan access-token path (Dhan Web token, RenewToken) is
# documented as 24h — assumed here too, same "no persisted refresh token,
# just re-login before assumed expiry" shape as FyersAuth, chosen over
# relying on DhanLogin.renew_token() since the docs describe renewal in
# terms of "Dhan Web" tokens specifically and its applicability to a
# TOTP-origin token is unconfirmed.
ASSUMED_VALIDITY = timedelta(hours=24)


class DhanAuth(AuthProvider):
    """TOTP + PIN login via Dhan's own documented `generateAccessToken`
    endpoint (unlike FyersAuth, this is the official flow, not a
    reverse-engineered one). `login()` computes a fresh TOTP code and does
    a full fresh login every call — no persisted refresh_token, matching
    GrowwAuth/FyersAuth ergonomics.

    `access_token` passthrough (like Fyers'/Upstox's): Dhan rate-limits
    `generateAccessToken` to **once every 2 minutes** (verified live — the
    endpoint returns {'status': 'error', 'message': 'Token can be generated
    once every 2 minutes.'}). Passing an already-generated token seeds it
    directly and skips the login call, so re-running within 2 minutes (or
    reusing a token across process restarts) doesn't hit the limit. pin +
    totp_secret are still needed for the 24h refresh; if only access_token
    is given, the token just expires after ~24h with no headless refresh.
    """

    def __init__(
        self,
        client_id: str,
        pin: str | None = None,
        totp_secret: str | None = None,
        access_token: str | None = None,
    ):
        if not client_id:
            raise AuthenticationError("client_id is required")
        if not access_token and not (pin and totp_secret):
            raise AuthenticationError(
                "either access_token, or both pin and totp_secret, are required"
            )
        self.client_id = client_id
        self.pin = pin
        self.totp_secret = totp_secret
        self._login = DhanLogin(client_id)
        self._token = (
            AuthToken(token=access_token, expires_at=datetime.now(IST) + ASSUMED_VALIDITY)
            if access_token
            else None
        )

    async def login(self) -> AuthToken:
        if not (self.pin and self.totp_secret):
            raise AuthenticationError(
                "cannot login/refresh without pin and totp_secret (only a static "
                "access_token was provided, and Dhan has no headless token refresh)"
            )
        otp = pyotp.TOTP(self.totp_secret).now()
        response = await asyncio.to_thread(self._login.generate_token, self.pin, otp)
        raw = response.get("accessToken")
        if not raw:
            raise AuthenticationError(f"Dhan generateAccessToken failed: {response}")
        self._token = AuthToken(token=raw, expires_at=datetime.now(IST) + ASSUMED_VALIDITY)
        return self._token
