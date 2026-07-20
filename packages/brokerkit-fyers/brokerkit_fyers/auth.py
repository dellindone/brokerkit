import asyncio
import hashlib
from datetime import datetime, timedelta

import requests
from fyers_apiv3.fyersModel import Config

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import IST

# Fyers access tokens live ~24h from issuance — unlike Groww's deterministic
# 6 AM IST expiry, there's no fixed clock time and the SDK doesn't hand us
# back an exact issued-at timestamp, so we can't compute a precise expiry.
# We assume a conservative validity window from construction/refresh time
# and additionally refresh on a fixed proactive interval (see broker.py's
# _auto_refresh_loop) rather than trusting the guess right up to the edge.
ASSUMED_VALIDITY = timedelta(hours=23)
REFRESH_INTERVAL = timedelta(hours=6)

REFRESH_ENDPOINT = f"{Config.API}/validate-refresh-token"


class FyersAuth(AuthProvider):
    """Wraps Fyers' /validate-refresh-token endpoint.

    Not part of the official SDK — fyers_apiv3.SessionModel only wraps the
    one-time browser step (/validate-authcode). This class assumes that
    step has already happened once outside the framework (see the package
    README / login_helper.py) and you're handing it the resulting
    access_token + refresh_token. From there it silently refreshes the
    access_token for up to 15 days using refresh_token + the account's
    trading PIN — same role as GrowwBroker's auto-refresh loop, just a
    different trigger (PIN, not TOTP) and a hand-rolled HTTP call instead
    of an SDK method.
    """

    def __init__(
        self,
        client_id: str,
        secret_key: str,
        pin: str,
        access_token: str,
        refresh_token: str,
    ):
        if not all([client_id, secret_key, pin, access_token, refresh_token]):
            raise AuthenticationError(
                "client_id, secret_key, pin, access_token and refresh_token are all required"
            )
        self.client_id = client_id
        self.secret_key = secret_key
        self.pin = pin
        self.refresh_token = refresh_token
        self._token = AuthToken(
            token=access_token, expires_at=datetime.now(IST) + ASSUMED_VALIDITY
        )

    def _app_id_hash(self) -> str:
        return hashlib.sha256(f"{self.client_id}:{self.secret_key}".encode()).hexdigest()

    async def login(self) -> AuthToken:
        """Refreshes via refresh_token + pin. Raises AuthenticationError if
        the refresh_token itself has expired (>15 days) — at that point
        there's no programmatic recovery, the browser login step has to be
        redone (see login_helper.py) and the broker recreated.
        """
        payload = {
            "grant_type": "refresh_token",
            "appIdHash": self._app_id_hash(),
            "refresh_token": self.refresh_token,
            "pin": self.pin,
        }
        response = await asyncio.to_thread(requests.post, REFRESH_ENDPOINT, json=payload)
        data = response.json()
        if data.get("s") != "ok" or "access_token" not in data:
            raise AuthenticationError(
                data.get("message") or "Fyers token refresh failed — refresh_token may have expired; re-run login_helper.py"
            )
        # Fyers may or may not rotate the refresh_token on each call; keep the old one if not returned.
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self._token = AuthToken(
            token=data["access_token"], expires_at=datetime.now(IST) + ASSUMED_VALIDITY
        )
        return self._token
