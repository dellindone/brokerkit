"""Fyers authentication."""

import asyncio
import base64
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import requests
from fyers_apiv3.fyersModel import SessionModel

from brokerkit.exceptions import AuthenticationError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.models.auth import AuthToken
from brokerkit.utils.datetime import IST

# Fyers gives no reliable expiry signal back (no fixed daily reset like
# Groww's 6 AM IST) — assume a conservative validity window and re-login
# well before it rather than trust a guessed timestamp to the edge.
ASSUMED_VALIDITY = timedelta(hours=20)

_LOGIN_OTP_URL = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
_VERIFY_OTP_URL = "https://api-t2.fyers.in/vagator/v2/verify_otp"
_VERIFY_PIN_URL = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
_TOKEN_URL = "https://api-t1.fyers.in/api/v3/token"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("ascii")).decode("ascii")


class FyersAuth(AuthProvider):
    """TOTP + PIN login — NOT Fyers' official flow (that's browser-redirect
    only, wrapped by fyers_apiv3.fyersModel.SessionModel). This plays back
    the same internal endpoints Fyers' own web login uses
    (api-t2.fyers.in/vagator/v2/*), the way a known community pattern does
    — chosen over the official browser-bootstrap design (2026-07-20,
    superseding that decision) after verifying against the user's own
    previously-working implementation of this exact flow, which is
    stronger evidence than the secondhand community script this was
    originally cross-checked against. Matches GrowwAuth's ergonomics: pure
    credentials in, `login()` does a full fresh login every time, no
    manual step, no persisted refresh_token to track.

    Trade-off, stated plainly: this isn't part of any Fyers SDK or public
    API contract — it drives the sequence the Fyers *website* itself uses
    internally, not a documented integration surface. It could break
    without notice on a UI/security change on Fyers' end, unlike the
    official OAuth-style flow. The auth_code -> access_token exchange at
    the end of `_login_sync` IS the official, documented step
    (SessionModel.generate_token()) — only the auth_code acquisition
    before it is unofficial.
    """

    def __init__(
        self,
        client_id: str,
        secret_key: str,
        redirect_uri: str,
        fy_id: str,
        totp_secret: str,
        pin: str,
    ):
        if not all([client_id, secret_key, redirect_uri, fy_id, totp_secret, pin]):
            raise AuthenticationError(
                "client_id, secret_key, redirect_uri, fy_id, totp_secret and pin are all required"
            )
        self.client_id = client_id
        self.secret_key = secret_key
        self.redirect_uri = redirect_uri
        self.fy_id = fy_id
        self.totp_secret = totp_secret
        self.pin = pin
        self._token = None

    async def login(self) -> AuthToken:
        raw = await asyncio.to_thread(self._login_sync)
        self._token = AuthToken(token=raw, expires_at=datetime.now(IST) + ASSUMED_VALIDITY)
        return self._token

    def _login_sync(self) -> str:
        otp_resp = requests.post(
            _LOGIN_OTP_URL, json={"fy_id": _b64(self.fy_id), "app_id": "2"}
        ).json()
        if otp_resp.get("s") != "ok":
            raise AuthenticationError(f"Fyers login step 1 (send_login_otp) failed: {otp_resp.get('message')}")

        # Avoid submitting a TOTP code that's about to rotate out from under us.
        if time.localtime().tm_sec % 30 > 27:
            time.sleep(5)
        otp_resp = requests.post(
            _VERIFY_OTP_URL,
            json={"request_key": otp_resp["request_key"], "otp": pyotp.TOTP(self.totp_secret).now()},
        ).json()
        if otp_resp.get("s") != "ok":
            raise AuthenticationError(f"Fyers login step 2 (verify_otp/TOTP) failed: {otp_resp.get('message')}")

        session = requests.Session()
        pin_resp = session.post(
            _VERIFY_PIN_URL,
            json={"request_key": otp_resp["request_key"], "identity_type": "pin", "identifier": _b64(self.pin)},
        ).json()
        if pin_resp.get("s") != "ok":
            raise AuthenticationError(f"Fyers login step 3 (verify_pin) failed: {pin_resp.get('message')}")

        session.headers.update({"authorization": f"Bearer {pin_resp['data']['access_token']}"})
        token_resp = session.post(
            _TOKEN_URL,
            json={
                "fyers_id": self.fy_id,
                "app_id": self.client_id[:-4],
                "redirect_uri": self.redirect_uri,
                "appType": "100",
                "response_type": "code",
                "create_cookie": True,
            },
        ).json()
        if token_resp.get("s") != "ok":
            raise AuthenticationError(f"Fyers login step 4 (internal token) failed: {token_resp.get('message')}")

        auth_code = parse_qs(urlparse(token_resp["Url"]).query).get("auth_code", [None])[0]
        if not auth_code:
            raise AuthenticationError("Fyers login: no auth_code in redirect URL")

        # From here on it's the official, documented step: exchange
        # auth_code for an access_token via SessionModel.generate_token().
        app_session = SessionModel(
            client_id=self.client_id,
            secret_key=self.secret_key,
            redirect_uri=self.redirect_uri,
            response_type="code",
            grant_type="authorization_code",
        )
        app_session.set_token(auth_code)
        final = app_session.generate_token()
        if not final or not final.get("access_token"):
            raise AuthenticationError(f"Fyers auth_code exchange failed: {final}")
        return final["access_token"]
