"""Daily browser login for Kite Connect.

Kite Connect has no programmatic login — no TOTP, no password grant, nothing
(verified against the SDK source and Zerodha's docs, not assumed). The only
way to mint an access_token is: open Zerodha's login page, log in there, and
catch the `request_token` that comes back on the redirect. This helper does
that with a local Flask server so nothing has to be copy-pasted out of the
address bar (the same mistake that truncated Fyers' long auth_code and cost
that adapter a debugging session).

Tokens expire at 6:00 AM IST the next day, so this is a once-a-day step.
Mint one and pass it to the broker to skip the browser for the rest of the
day:

    from brokerkit_zerodha import get_access_token

    token = get_access_token(
        api_key="...",
        api_secret="...",
        redirect_uri="http://127.0.0.1:5000/",
    )
    broker = await create_broker("zerodha", api_key=..., api_secret=...,
                                 access_token=token)

Or from the command line:
    python -m brokerkit_zerodha.login_helper <api_key> <api_secret> <redirect_uri>

The redirect_uri must match the one registered on developers.kite.trade
exactly. Note for macOS: AirPlay Receiver squats on port 5000 by default —
either disable it in System Settings or register a different port (this bit
the Upstox adapter too).
"""

import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

from flask import Flask, request
from kiteconnect import KiteConnect

_request_token: str | None = None
_app = Flask(__name__)


@_app.route("/")
def _capture():
    global _request_token
    _request_token = request.args.get("request_token")
    if _request_token:
        return "<h2>Login successful — you can close this tab.</h2>"
    # Kite redirects with ?status=error&... when the login itself fails.
    return (
        "<h2>No request_token in the redirect.</h2>"
        "<p>Check that redirect_uri matches the one registered for this app "
        "on developers.kite.trade.</p>"
    )


def get_access_token(
    api_key: str,
    api_secret: str,
    redirect_uri: str,
    return_refresh_token: bool = False,
) -> str | tuple[str, str | None]:
    """Open a browser for the Kite login, capture the redirect locally,
    exchange the request_token for an access_token, print and return it.

    With `return_refresh_token=True` returns `(access_token, refresh_token)`.
    The refresh_token is usually None: Zerodha only issues one to approved
    platforms, so a personal app cannot renew headlessly and has to redo this
    login each day.
    """
    global _request_token
    _request_token = None  # reset in case this runs more than once in-process

    port = urlparse(redirect_uri).port or 5000
    kite = KiteConnect(api_key=api_key)
    url = kite.login_url()

    threading.Thread(target=lambda: _app.run(port=port), daemon=True).start()
    time.sleep(1)  # let Flask bind before the browser hits it
    print(f"Opening for login:\n  {url}\n")
    webbrowser.open(url, new=1)

    print(f"Waiting for the redirect back to {redirect_uri} ...")
    while _request_token is None:
        time.sleep(1)
    print("Got request_token, exchanging for access_token...")

    # generate_session computes the sha256(api_key + request_token +
    # api_secret) checksum internally and calls set_access_token on success.
    data = kite.generate_session(_request_token, api_secret=api_secret)
    access_token = (data or {}).get("access_token")
    if not access_token:
        raise RuntimeError(f"Token exchange failed: {data}")

    refresh_token = (data or {}).get("refresh_token") or None
    print("access_token:", access_token)
    print("refresh_token:", refresh_token or "(none — expected for a personal app)")
    print("\nThis token is valid until 6:00 AM IST tomorrow.")

    if return_refresh_token:
        return access_token, refresh_token
    return access_token


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: python -m brokerkit_zerodha.login_helper "
            "<api_key> <api_secret> <redirect_uri>"
        )
    get_access_token(*sys.argv[1:4])
