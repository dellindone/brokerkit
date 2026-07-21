import asyncio
from datetime import time

from kiteconnect import KiteConnect

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import next_occurrence

# Kite access tokens die at 6:00 AM IST the following day. Zerodha calls this
# a regulatory requirement, and it is deterministic — the same shape as
# Groww's 6 AM expiry, and unlike Angel's jwt (which expires on a wall-clock
# boundary that depends on login time) or Fyers'/Upstox's (no expiry signal
# at all, so they assume). No token decoding is needed here: Kite's
# access_token is an opaque string, not a JWT, so there is no `exp` claim to
# read — the documented schedule is the only source of truth.
_EXPIRY_TIME = time(6, 0)


class ZerodhaAuth(AuthProvider):
    """Kite Connect login. Genuinely different from every other adapter here:
    **Kite has no programmatic login at all.**

    Verified against the SDK source and the official docs rather than
    assumed: `kiteconnect` 5.2.0 contains zero references to TOTP/2FA/
    password, and the docs describe only the browser flow — user opens
    `login_url()`, logs in on Zerodha's own page, and is redirected back with
    a `request_token` which `generate_session(request_token, api_secret)`
    exchanges for an access_token. So there is no Groww/Fyers/Dhan/Angel-style
    headless credential login to implement; this is the Upstox-OAuth
    situation.

    Consequences, all deliberate:

    * **The `access_token` passthrough earns its place here** (unlike the
      Angel adapter, where it was removed as a pure footgun). A daily browser
      login is unavoidable, so being able to mint a token once and reuse it
      across runs is the whole ergonomics story — exactly the Upstox/Dhan
      justification. Pass `access_token=` to skip the browser entirely.
    * **No unattended refresh.** `renew_access_token(refresh_token)` exists in
      the SDK, but Kite's docs restrict `refresh_token` issuance to "certain
      approved platforms", so a personal app generally never receives one.
      `refresh()` uses it when present and otherwise fails loudly rather than
      popping a browser window in a background task, where nobody could
      answer it.
    * `login()` opens a real browser. That is fine for an interactive first
      run and wrong for anything unattended, so it only happens when no
      access_token was supplied.

    Owns THE shared KiteConnect client. `KiteConnect._request` builds its
    Authorization header from `self.api_key` + `self.access_token` on every
    single call (verified in connect.py), so a refreshed token only has to be
    written to that one attribute for every provider to pick it up — the
    easy Groww/Upstox/Angel case, not Fyers'/Dhan's cached-header trap.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ):
        if not api_key or not api_secret:
            raise AuthenticationError("api_key and api_secret are required")
        if not access_token and not redirect_uri:
            raise AuthenticationError(
                "Either access_token (reuse a token you already minted) or "
                "redirect_uri (to run the browser login) is required — Kite "
                "Connect has no headless login."
            )
        self.api_key = api_key
        self.api_secret = api_secret
        self.redirect_uri = redirect_uri
        self.client = KiteConnect(api_key=api_key)
        self._passthrough = access_token
        self._refresh_token: str | None = None
        self._token: AuthToken | None = None

    def _wrap(self, access_token: str) -> AuthToken:
        self.client.set_access_token(access_token)
        self._token = AuthToken(
            token=access_token,
            expires_at=next_occurrence(_EXPIRY_TIME),
        )
        return self._token

    async def login(self) -> AuthToken:
        """Reuse a passed-in access_token if given, else run the browser
        login. The passthrough is consumed once: if it turns out to be stale
        and a caller re-logs in, the browser flow runs instead of silently
        re-wrapping the same dead token (the exact failure that poisoned the
        Angel adapter for hours)."""
        if self._passthrough:
            token, self._passthrough = self._passthrough, None
            return self._wrap(token)

        if not self.redirect_uri:
            raise AuthenticationError(
                "Kite access_token expired and no redirect_uri was configured, "
                "so the browser login cannot be run. Mint a new token with "
                "brokerkit_zerodha.get_access_token(...) and pass it as "
                "access_token=."
            )

        # Imported at call time, not module level, purely to keep the
        # dependency direction one-way (login_helper is a leaf; auth doesn't
        # pull a web server into its import graph). Flask is a hard dependency
        # of this package either way, and the top-level __init__ re-exports
        # get_access_token, so this is about structure, not about avoiding
        # the install.
        from brokerkit_zerodha.login_helper import get_access_token

        access_token, refresh_token = await asyncio.to_thread(
            get_access_token,
            self.api_key,
            self.api_secret,
            self.redirect_uri,
            True,  # return_refresh_token
        )
        self._refresh_token = refresh_token
        return self._wrap(access_token)

    async def refresh(self) -> AuthToken:
        """Kite's own token renewal — only usable if login actually handed
        back a refresh_token, which Zerodha issues to approved platforms
        only. Raises a clear error otherwise instead of opening a browser
        from a background task."""
        if not self._refresh_token:
            raise AuthenticationError(
                "Kite Connect issued no refresh_token for this app (Zerodha "
                "restricts them to approved platforms), so the session cannot "
                "be renewed without a browser login. Re-run "
                "brokerkit_zerodha.get_access_token(...) and rebuild the "
                "broker with the new access_token."
            )
        response = await asyncio.to_thread(
            self.client.renew_access_token, self._refresh_token, self.api_secret
        )
        access_token = (response or {}).get("access_token")
        if not access_token:
            raise AuthenticationError(f"Kite renew_access_token failed: {response}")
        return self._wrap(access_token)

    async def get_token(self) -> AuthToken:
        if self._token is None:
            return await self.login()
        if self._token.is_expired:
            return await self.refresh()
        return self._token
