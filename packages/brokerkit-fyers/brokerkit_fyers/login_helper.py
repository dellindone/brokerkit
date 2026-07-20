"""One-time browser login to activate a new Fyers API app.

A brand-new Fyers app needs one official browser-based auth_code login
before TOTP-based auto-login (FyersAuth) works on it — see the package
README. Call get_access_token() once with your app's credentials; it
opens a browser, catches the redirect with a local Flask server (no
manual copy-paste — that truncates the long JWT auth_code and fails), and
returns a fresh access_token as proof the app + credentials work end to
end.

    from brokerkit_fyers import get_access_token

    get_access_token(
        client_id="XC4EOD67IM-100",
        secret_key="...",
        redirect_uri="http://127.0.0.1:5000/",
    )

Or from the command line:
    python -m brokerkit_fyers.login_helper <client_id> <secret_key> <redirect_uri>
"""

import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

from flask import Flask, request
from fyers_apiv3.fyersModel import SessionModel

_auth_code: str | None = None
_app = Flask(__name__)


@_app.route("/")
def _capture():
    global _auth_code
    _auth_code = request.args.get("auth_code")
    if _auth_code:
        return "<h2>Login successful — you can close this tab.</h2>"
    return "<h2>No auth_code in the redirect — check redirect_uri matches your app config.</h2>"


def get_access_token(client_id: str, secret_key: str, redirect_uri: str) -> str:
    """Opens a browser for login, captures the redirect locally (no
    manual copy-paste), exchanges the auth_code for an access_token,
    prints and returns it.
    """
    global _auth_code
    _auth_code = None  # reset in case this is called more than once in-process

    port = urlparse(redirect_uri).port or 5000
    session = SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code",
        state="brokerkit",
    )
    url = session.generate_authcode()

    threading.Thread(target=lambda: _app.run(port=port), daemon=True).start()
    time.sleep(1)  # let Flask bind before the browser hits it
    print(f"Opening for login:\n  {url}\n")
    webbrowser.open(url, new=1)

    print(f"Waiting for the redirect back to {redirect_uri} ...")
    while _auth_code is None:
        time.sleep(1)
    print("Got auth_code, exchanging for access_token...")

    # SessionModel.generate_token() computes appIdHash internally and
    # posts to /validate-authcode — no need to hand-roll that call.
    session.set_token(_auth_code)
    data = session.generate_token()
    if not data or not data.get("access_token"):
        raise RuntimeError(f"Token exchange failed: {data}")

    print("access_token:", data["access_token"])
    print(
        "\nThis confirms the app + auth_code exchange works end-to-end. If "
        "FyersAuth's TOTP+PIN auto-login is failing separately, that's a "
        "different step (2FA verification), not this one."
    )
    return data["access_token"]


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: python -m brokerkit_fyers.login_helper <client_id> <secret_key> <redirect_uri>"
        )
    get_access_token(*sys.argv[1:4])
