"""Angel One authentication."""

import asyncio
import base64
import binascii
import json
from datetime import datetime, timedelta

import pyotp
from SmartApi.smartConnect import SmartConnect

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import IST

# Angel's jwt is SHORT-LIVED — ~65 minutes, NOT a day. Live-verified
# 2026-07-21 by decoding a real token: iat 22:54:53 -> exp 00:00:00 (and the
# feedToken issued in the same response carries a full 24h, so the two are
# genuinely different lifetimes). An earlier assumed-24h validity made a
# 4-hour-old token look fresh, so the refresh never fired and every REST call
# returned AG8001 "Invalid Token" — the real expiry is read off the token
# itself now, and this constant is only the fallback if that ever fails.
#
# This is also exactly why Angel ships a refresh-token endpoint when no other
# broker here does: at ~1h validity, `generateToken(refreshToken)` (no TOTP)
# is the only practical way to stay logged in. See refresh().
_ASSUMED_VALIDITY = timedelta(minutes=60)
# Refresh a little before the real expiry rather than racing it.
_EXPIRY_SAFETY = timedelta(minutes=2)


def _expiry_from_jwt(token: str) -> datetime | None:
    """Read the `exp` claim straight off the jwt payload. No signature check —
    this only needs the expiry, and Angel gives no expiry field anywhere in
    the login response body."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=IST) - _EXPIRY_SAFETY


def _token_from_jwt(token: str) -> AuthToken:
    expires_at = _expiry_from_jwt(token) or (datetime.now(IST) + _ASSUMED_VALIDITY)
    return AuthToken(token=token, expires_at=expires_at)


class AngelAuth(AuthProvider):
    """TOTP + MPIN login via SmartConnect.generateSession, then Angel's own
    native refresh-token flow (generateToken) for the daily refresh.

    Unlike Groww/Fyers/Dhan (which all re-run a full fresh login every
    refresh — they have no refresh-token endpoint), Angel returns a
    refreshToken from login and `generateToken(refreshToken)` mints a fresh
    jwt without another TOTP. refresh() uses that, falling back to a full
    login() only if it fails (e.g. the refresh token itself expired).

    Owns THE shared SmartConnect client — the broker reuses `auth.client`
    for every REST provider. SmartConnect._request re-reads `self.access_token`
    fresh on every call (verified in smartConnect.py, like Groww/Upstox and
    unlike Fyers/Dhan's cached header), so a refresh only needs to mutate
    that one attribute for all providers to pick it up.

    Deliberately NO token passthrough, unlike the Fyers/Upstox/Dhan adapters.
    Theirs earn it — Dhan rate-limits token generation to once per 2 minutes,
    Upstox needs an interactive browser login daily. Angel has neither problem:
    login is fully headless and takes about a second, and the jwt only lives
    ~65 minutes anyway, so a hand-pasted token is stale almost immediately.
    It was a pure footgun in practice — a stale pasted token made every call
    fail AG8001 for hours (2026-07-21) — so credentials are the only way in.
    """

    def __init__(self, api_key: str, client_code: str, mpin: str, totp_secret: str):
        if not (api_key and client_code and mpin and totp_secret):
            raise AuthenticationError(
                "api_key, client_code, mpin and totp_secret are all required"
            )
        self.api_key = api_key
        self.client_code = client_code
        self.mpin = mpin
        self.totp_secret = totp_secret
        # SmartConnect.__init__ makes a `logs/<date>/app.log` dir in the cwd
        # and (at import time, once) a blocking ipify call whose result it
        # then discards for a hardcoded IP — both are SDK quirks, documented
        # in the adapter README; neither is worked around here.
        self.client = SmartConnect(api_key=api_key)
        self._refresh_token: str | None = None
        self._token: AuthToken | None = None

    @property
    def feed_token(self) -> str | None:
        return self.client.getfeedToken()

    async def login(self) -> AuthToken:
        otp = pyotp.TOTP(self.totp_secret).now()
        response = await asyncio.to_thread(
            self.client.generateSession, self.client_code, self.mpin, otp
        )
        # generateSession returns the getProfile response on success (it has
        # data.jwtToken) or the raw login envelope {status: false, ...} on
        # failure. On success it has already set access/refresh/feed tokens
        # on the client via setAccessToken/etc — read them back from there
        # (the returned jwtToken is "Bearer "-prefixed; the client's is raw).
        if not isinstance(response, dict) or not response.get("status"):
            raise AuthenticationError(f"Angel generateSession failed: {response}")
        jwt = self.client.access_token
        if not jwt:
            raise AuthenticationError(f"Angel login returned no jwt: {response}")
        self._refresh_token = self.client.refresh_token
        self._token = _token_from_jwt(jwt)
        return self._token

    async def refresh(self) -> AuthToken:
        """Angel's native refresh: generateToken(refreshToken) mints a fresh
        jwt (+ feed token) without another TOTP. Falls back to a full login()
        if there's no refresh token or the endpoint rejects it."""
        if not self._refresh_token:
            return await self.login()
        try:
            response = await asyncio.to_thread(
                self.client.generateToken, self._refresh_token
            )
        except Exception:
            return await self.login()
        if not isinstance(response, dict) or not response.get("status"):
            return await self.login()
        jwt = self.client.access_token  # generateToken calls setAccessToken
        if not jwt:
            return await self.login()
        self._token = _token_from_jwt(jwt)
        return self._token

    async def get_token(self) -> AuthToken:
        if self._token is None:
            return await self.login()
        if self._token.is_expired:
            return await self.refresh()
        return self._token
