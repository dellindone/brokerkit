import json
from contextlib import contextmanager
from typing import Iterator

from upstox_client.rest import ApiException

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError

# Verified against Upstox's documented error-codes page — these are the
# auth/token-specific ones (invalid credentials/token, restricted
# extended_token scope, inactive client_id); everything else goes to the
# caller's `default` instead, same role as Groww's `groww_errors(default)`.
_AUTH_CODES = {"UDAPI100016", "UDAPI100050", "UDAPI100067", "UDAPI100073"}


def _error_codes(body: str | None) -> set[str]:
    if not body:
        return set()
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return set()
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    if not isinstance(errors, list):
        return set()
    return {e.get("error_code") or e.get("errorCode") for e in errors if isinstance(e, dict)}


@contextmanager
def upstox_errors(default: type[BrokerKitError] = BrokerKitError) -> Iterator[None]:
    """Wraps SDK calls; ApiException (Upstox's SDK raises this on any
    non-2xx response, verified from rest.py) becomes a core exception.

    `default`: used when the error isn't specifically auth-related —
    caller decides its own domain (e.g. OrderError from the order provider).
    """
    try:
        yield
    except ApiException as e:
        codes = _error_codes(e.body)
        message = f"Upstox API error ({e.status} {e.reason}): {e.body}"
        if e.status in (401, 403) or codes & _AUTH_CODES:
            raise AuthenticationError(message) from e
        raise default(message) from e
