"""Run this ONCE manually to bootstrap Fyers auth.

Fyers' official auth flow needs a one-time interactive browser login (no
official way around it — see the brokerkit-fyers README for why). This
script does that flow and prints the access_token + refresh_token you then
pass to FyersBroker.create(...) / create_broker("fyers", ...). The
access_token is only valid ~24h, but the refresh_token lets FyersBroker
self-refresh (via your trading PIN) for up to 15 days without repeating
this step — see brokerkit_fyers/auth.py.

Usage:
    python login_helper.py

You'll need, from your Fyers API app (https://myapi.fyers.in/dashboard):
    - client_id      (the App ID, e.g. "XC4EOD67IM-100")
    - secret_key     (the App Secret)
    - redirect_uri   (exactly what you registered for the app)
"""

import hashlib
import webbrowser
from urllib.parse import parse_qs, urlparse

import requests
from fyers_apiv3.fyersModel import Config, SessionModel


def main() -> None:
    client_id = input("client_id: ").strip()
    secret_key = input("secret_key: ").strip()
    redirect_uri = input("redirect_uri: ").strip()

    session = SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code",
        state="brokerkit",
    )
    url = session.generate_authcode()
    print(f"\nOpening for login:\n  {url}\n")
    webbrowser.open(url, new=1)

    print(
        "After you log in, Fyers redirects to your redirect_uri with an "
        "?auth_code=...&state=... query string. Paste that full redirected "
        "URL (or just the auth_code value) below."
    )
    pasted = input("redirected URL or auth_code: ").strip()
    if pasted.startswith("http"):
        auth_code = parse_qs(urlparse(pasted).query)["auth_code"][0]
    else:
        auth_code = pasted

    app_id_hash = hashlib.sha256(f"{client_id}:{secret_key}".encode()).hexdigest()
    response = requests.post(
        f"{Config.API}{Config.generate_access_token}",
        json={"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code},
    )
    data = response.json()
    if data.get("s") != "ok":
        raise SystemExit(f"Token exchange failed: {data}")

    print("\n--- save these ---")
    print("access_token: ", data["access_token"])
    print("refresh_token:", data["refresh_token"])
    print(
        "\nrefresh_token is valid ~15 days; FyersBroker refreshes access_token "
        "automatically using it + your trading PIN until then. Re-run this "
        "script after that (or on refresh failure)."
    )


if __name__ == "__main__":
    main()
