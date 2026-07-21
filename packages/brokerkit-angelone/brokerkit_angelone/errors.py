from contextlib import contextmanager
from typing import Any, Iterator

from SmartApi.smartExceptions import (
    PermissionException,
    SmartAPIException,
    TokenException,
)

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError

# SmartConnect handles API failures two different ways (both verified in
# smartConnect.py's _request), so translation has to cover both:
#
#   1. It RAISES a SmartAPIException subclass only when the JSON body carries
#      an "error_type" key (a Kite-Connect-style field Angel rarely returns).
#      -> caught by angel_errors() below.
#   2. Far more commonly, a business failure comes back as a normal 200-ish
#      body {"status": false, "message": "...", "errorcode": "AB1004",
#      "data": null} and is NOT raised — _request just logs and returns it.
#      -> caught by check() below, which inspects `status`.
#
# So providers do both: wrap the SDK call in `with angel_errors(Default):`
# (for case 1) and then pass the returned dict through `check(resp, Default)`
# (for case 2) — same inspect-don't-only-catch approach as the Fyers adapter.

# Angel error codes that mean "your auth/session can't do this". From Angel's
# published error-code list: AG8001 (Invalid Token), AG8002 (Token Expired),
# AG8003 (Token missing), AB1010 (session/access related). All AG-prefixed
# codes are token/gateway-auth errors. Written from the docs; a live 401/403
# response would confirm the exact code but the auth->AuthenticationError
# routing holds regardless.
_AUTH_CODES = {"AG8001", "AG8002", "AG8003", "AB1010", "AB8050", "AB8051"}


def _is_auth_code(code: Any) -> bool:
    if not code:
        return False
    code = str(code)
    return code in _AUTH_CODES or code.startswith("AG")


@contextmanager
def angel_errors(default: type[BrokerKitError] = BrokerKitError) -> Iterator[None]:
    """Translate raised SmartAPIExceptions (case 1 above). Token/permission
    errors -> AuthenticationError; anything else -> `default` (the caller's
    domain error, e.g. OrderError)."""
    try:
        yield
    except (TokenException, PermissionException) as e:
        raise AuthenticationError(str(e)) from e
    except SmartAPIException as e:
        raise default(str(e)) from e


def check(response: Any, default: type[BrokerKitError] = BrokerKitError) -> Any:
    """Success -> return the unwrapped `data`. `status: false` -> raise (auth
    codes as AuthenticationError, everything else as `default`)."""
    if not isinstance(response, dict):
        raise default(f"Unexpected Angel response (not a dict): {response!r}")

    # Angel's envelope is genuinely inconsistent between layers (live-verified
    # 2026-07-21): the *services* answer {"status": true/false, ...,
    # "errorcode": ...}, but a gateway-level auth rejection answers
    # {"success": false, "message": "Invalid Token", "errorCode": "AG8001"} —
    # different success key AND different case on the error-code key. Both
    # spellings are accepted here rather than assuming one shape.
    if response.get("status") in (True, "true") or response.get("success") in (True, "true"):
        return response.get("data")

    code = response.get("errorcode") or response.get("errorCode")
    message = response.get("message") or f"Angel API error; raw={response!r}"

    if _is_auth_code(code):
        raise AuthenticationError(f"[{code}] {message}")
    raise default(f"[{code}] {message}" if code else message)
