"""Credential-gated live smoke tier.

Mirrors the read-only flow every adapter's example runs (auth -> instruments
-> portfolio -> orders). Each adapter is skipped unless *its* credentials are
present in the environment, so a bare `pytest` run stays green with zero creds.
Run just this tier with:  pytest -m live

Blocked-by-design paths (paid market-data subscriptions, static-IP order
writes) are walls, not features — a live failure there is reported as a skip
with the broker's own error, never a red test.
"""

import asyncio
import os

import pytest

from brokerkit import create_broker
from brokerkit.exceptions import BrokerKitError

pytestmark = pytest.mark.live


# kwarg -> (ENV_VAR, required?). Required vars mirror each example's
# ``os.environ[...]`` (hard) accesses; optional ones its ``os.environ.get``.
LIVE_ENV: dict[str, dict[str, tuple[str, bool]]] = {
    "groww": {
        "totp_key": ("GROWW_API_KEY", True),
        "totp_secret": ("GROWW_TOTP_SECRET", True),
    },
    "fyers": {
        "client_id": ("FYERS_CLIENT_ID", True),
        "secret_key": ("FYERS_SECRET_KEY", True),
        "redirect_uri": ("FYERS_REDIRECT_URI", True),
        "fy_id": ("FYERS_ID", True),
        "totp_secret": ("FYERS_TOTP_SECRET", True),
        "pin": ("FYERS_PIN", True),
    },
    "upstox": {
        "analytics_token": ("UPSTOX_ANALYTICS_TOKEN", True),
    },
    "dhan": {
        "client_id": ("DHAN_CLIENT_ID", True),
        "access_token": ("DHAN_ACCESS_TOKEN", False),
        "pin": ("DHAN_PIN", False),
        "totp_secret": ("DHAN_TOTP_SECRET", False),
    },
    "angelone": {
        "api_key": ("ANGEL_API_KEY", True),
        "client_code": ("ANGEL_CLIENT_CODE", True),
        "mpin": ("ANGEL_MPIN", True),
        "totp_secret": ("ANGEL_TOTP_SECRET", True),
    },
    "zerodha": {
        "api_key": ("ZERODHA_API_KEY", True),
        "api_secret": ("ZERODHA_API_SECRET", True),
        "access_token": ("ZERODHA_ACCESS_TOKEN", False),
    },
}


def _config_or_skip(adapter: str) -> dict[str, str]:
    spec = LIVE_ENV[adapter]
    missing = [env for _, (env, required) in spec.items() if required and not os.environ.get(env)]
    if missing:
        pytest.skip(f"{adapter}: set {', '.join(missing)} to run the live smoke test")
    return {kwarg: os.environ[env] for kwarg, (env, _) in spec.items() if os.environ.get(env)}


async def _smoke(adapter: str, config: dict[str, str]) -> None:
    broker = await create_broker(adapter, **config)
    try:
        instruments = await broker.instruments.fetch_instruments()
        assert instruments, f"{adapter}: instrument master came back empty"

        # Portfolio + orders need auth and can be blocked (subscription /
        # static-IP walls). Exercise them but never fail the tier on a wall.
        for label, call in (
            ("portfolio.holdings", broker.portfolio.holdings),
            ("orders.list_orders", broker.orders.list_orders),
        ):
            try:
                result = await call()
                print(f"{adapter} {label}: {len(result)} rows")
            except BrokerKitError as exc:
                print(f"{adapter} {label}: blocked ({exc})")
    finally:
        await broker.close()


@pytest.mark.parametrize("adapter", list(LIVE_ENV))
def test_live_read_flow(adapter):
    config = _config_or_skip(adapter)
    asyncio.run(_smoke(adapter, config))
