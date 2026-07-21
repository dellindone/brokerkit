"""Fyers error translation into core exceptions."""

from typing import Any

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError

# Confirmed from fyersModel.py's FyersServiceSync/Async: Fyers API calls
# never raise on a Fyers-side failure — they return {"s": "error", "code":
# ..., "message": ...} even for auth errors. `code` is dual-purpose: the
# exception branches in the SDK sometimes stuff the raw HTTP status code in
# there (401/403/...), other times it's one of Fyers' own negative business
# codes (see the official Postman collection's error-codes sheet — -371
# "invalid appIdHash", -374 "missing/invalid auth_code" are the two
# confirmed-auth-related ones from that sheet; the rest of that sheet is
# order-validation-specific and goes to the caller's `default` instead).
_AUTH_CODES = {401, 403, -371, -374}


def check(data: Any, default: type[BrokerKitError] = BrokerKitError) -> dict:
    """Fyers response dicts don't raise — inspect `s` and translate.

    `default`: domain exception to use when the code isn't specifically
    recognized as auth-related (caller decides — e.g. OrderError from the
    order provider). Same role as Groww's `groww_errors(default)`, just a
    plain function instead of a context manager since there's no exception
    to catch here, only a response body to inspect.
    """
    if not isinstance(data, dict) or data.get("s") != "error":
        return data
    message = data.get("message") or "Fyers API error"
    if data.get("code") in _AUTH_CODES:
        raise AuthenticationError(message)
    raise default(message)
