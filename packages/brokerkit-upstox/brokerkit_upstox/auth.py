"""Upstox authentication."""

import asyncio
import threading
import time
import webbrowser
from datetime import datetime, time as dtime, timedelta
from urllib.parse import urlencode, urlparse

from flask import Flask, request
from upstox_client import ApiClient, Configuration, LoginApi
from upstox_client.rest import ApiException

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import IST, next_occurrence

_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
_API_VERSION = "2.0"
# No documented expiry field on TokenResponse (verified from the SDK's
# token_response.py) — Upstox's own docs state access_token validity runs
# until 3:30 AM IST the *next* day regardless of generation time, same
# deterministic-reset shape as Groww's 6 AM IST (unlike Fyers, which gives
# no reliable signal at all and needs an assumed window).
TOKEN_EXPIRY_TIME = dtime(3, 30)

# 1-year validity per Upstox's Analytics Token docs; re-check well before
# the real deadline rather than trust the exact boundary.
_ANALYTICS_TOKEN_VALIDITY = timedelta(days=360)

# 30-day validity per Upstox's Sandbox docs; same margin-before-deadline
# reasoning as the Analytics Token above.
_SANDBOX_TOKEN_VALIDITY = timedelta(days=27)


class UpstoxAnalyticsAuth(AuthProvider):
    """Wraps a dashboard-generated Analytics Token (Upstox Developer Apps
    page, Analytics tab) — no login flow, no refresh: it's a static,
    long-lived (1-year), read-only Bearer token. Powers market/historical/
    option-chain/fundamentals/news; cannot place orders or read
    account-scoped Portfolio (that needs UpstoxOAuth instead).
    """

    def __init__(self, analytics_token: str):
        if not analytics_token:
            raise AuthenticationError("analytics_token is required")
        self._token = AuthToken(
            token=analytics_token, expires_at=datetime.now(IST) + _ANALYTICS_TOKEN_VALIDITY
        )

    async def login(self) -> AuthToken:
        return self._token


class UpstoxSandboxAuth(AuthProvider):
    """Wraps a dashboard-generated Sandbox token (Upstox Developer Apps
    page, dedicated sandbox app — only one per user, `Generate` button, no
    browser login flow, same mechanics as `UpstoxAnalyticsAuth`) — static,
    30-day, order-writes-only. Verified from the SDK's own
    `Configuration(sandbox=True)`/`sandbox_urls`: sandbox mode allows
    *only* `place`/`modify`/`cancel`/`multi-place` order paths (v2 and
    v3) — no order reads, no portfolio, no market data. The SDK itself
    raises `ValueError` client-side for anything outside that allowlist,
    before even hitting the network.
    """

    def __init__(self, sandbox_token: str):
        if not sandbox_token:
            raise AuthenticationError("sandbox_token is required")
        self._token = AuthToken(
            token=sandbox_token, expires_at=datetime.now(IST) + _SANDBOX_TOKEN_VALIDITY
        )

    async def login(self) -> AuthToken:
        return self._token


class UpstoxOAuth(AuthProvider):
    """Official OAuth2 authorization-code flow — the only Upstox-documented
    way to get an order/portfolio-capable token (Analytics Token can't do
    either). `login()` opens a browser and runs a local Flask server on
    `redirect_uri` to capture the `code` param programmatically (same
    no-copy-paste technique as Fyers' login_helper.py — Upstox's `code` is
    a JWT-like string, manual copy-paste is as failure-prone here as it was
    there).

    Unlike Groww/Fyers, this can NOT be refreshed headlessly in the
    background: there is no documented programmatic login for this token
    (only the Analytics Token is headless, and it can't do orders/
    portfolio). `login()` re-runs this full interactive browser flow every
    time it's called — including on every refresh once the token's
    assumed 3:30 AM IST expiry passes. Something needs to be watching a
    browser tab for this to succeed; that's a real, deliberate limitation
    of the orders/portfolio path, not an oversight — see ROADMAP Phase 10.

    `access_token` is an escape hatch for an already-obtained token (e.g.
    grabbed manually once, or reused within the same day) — skips the
    browser flow entirely until it expires. At least one of `access_token`
    or the three client credentials must be given; both can be given
    together so an expired manually-supplied token still refreshes via
    browser login rather than dead-ending.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ):
        has_creds = bool(client_id and client_secret and redirect_uri)
        if not access_token and not has_creds:
            raise AuthenticationError(
                "UpstoxOAuth needs access_token and/or (client_id, client_secret, redirect_uri)"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._token = (
            AuthToken(token=access_token, expires_at=next_occurrence(TOKEN_EXPIRY_TIME))
            if access_token else None
        )

    async def login(self) -> AuthToken:
        if not (self.client_id and self.client_secret and self.redirect_uri):
            raise AuthenticationError(
                "Upstox access_token missing/expired and no client_id/client_secret/redirect_uri "
                "given to refresh via browser login — supply a fresh access_token."
            )
        code = await asyncio.to_thread(self._capture_code)
        api = LoginApi(ApiClient(Configuration()))
        try:
            resp = await asyncio.to_thread(
                api.token,
                _API_VERSION,
                code=code,
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                grant_type="authorization_code",
            )
        except ApiException as e:
            raise AuthenticationError(f"Upstox token exchange failed: {e.reason} — {e.body}") from e
        if not resp or not resp.access_token:
            raise AuthenticationError(f"Upstox token exchange returned no access_token: {resp}")
        self._token = AuthToken(token=resp.access_token, expires_at=next_occurrence(TOKEN_EXPIRY_TIME))
        return self._token

    def _capture_code(self) -> str:
        captured: dict[str, str | None] = {"code": None}
        app = Flask(__name__)

        @app.route("/")
        def _capture():
            captured["code"] = request.args.get("code")
            if captured["code"]:
                return "<h2>Login successful — you can close this tab.</h2>"
            return "<h2>No code in the redirect — check redirect_uri matches your app config.</h2>"

        port = urlparse(self.redirect_uri).port or 5000
        threading.Thread(target=lambda: app.run(port=port), daemon=True).start()
        time.sleep(1)  # let Flask bind before the browser hits it

        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
        })
        url = f"{_AUTHORIZE_URL}?{query}"
        print(f"Opening for Upstox login:\n  {url}\n")
        webbrowser.open(url, new=1)

        print(f"Waiting for the redirect back to {self.redirect_uri} ...")
        while captured["code"] is None:
            time.sleep(1)
        return captured["code"]


def get_access_token(client_id: str, client_secret: str, redirect_uri: str) -> str:
    """Mint a fresh Upstox access_token via the browser OAuth flow, without
    building a full UpstoxBroker — for manually refreshing a token stashed
    somewhere (e.g. a config.py constant) once the previous one dies at its
    ~3:30 AM IST expiry. Prints and returns the token.

        from brokerkit_upstox import get_access_token
        get_access_token(client_id="...", client_secret="...", redirect_uri="http://127.0.0.1:5000/")

    Or from the command line:
        python -m brokerkit_upstox.auth <client_id> <client_secret> <redirect_uri>
    """
    auth = UpstoxOAuth(client_id, client_secret, redirect_uri)
    token = asyncio.run(auth.login())
    print("access_token:", token.token)
    print(f"Valid until ~3:30 AM IST tomorrow ({token.expires_at}).")
    return token.token


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        raise SystemExit("Usage: python -m brokerkit_upstox.auth <client_id> <client_secret> <redirect_uri>")
    get_access_token(*sys.argv[1:4])
