from typing import Any

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError

# dhanhq's DhanHTTP never raises on an API-level failure — every call
# returns an envelope {status, remarks, data} (verified in dhan_http.py's
# _parse_response). `status` is 'success'/'failure'; on failure `remarks`
# is {error_code, error_type, error_message}, or a plain string when the
# transport itself failed (requests exception). `check()` inspects rather
# than catches, same shape as Fyers' errors.check().
#
# Auth-related codes from the Annexure "Trading API Error" table: DH-901
# (invalid/expired token) and DH-902 (no Trading/Data API access) both mean
# "your current auth/access can't do this" -> AuthenticationError. Codes
# from the Data API error table (websocket side, 807/808/809) also land
# here if a REST path ever surfaces one.
_AUTH_CODES = {"DH-901", "DH-902", "807", "808", "809", "810"}


def is_no_data(response: dict[str, Any]) -> bool:
    """Dhan returns holdings/positions "empty" as a *failure* envelope (e.g.
    DH-1111 "No holdings available"), not a 200 with []. Live-verified
    2026-07-21. Detect it so portfolio can return [] instead of raising."""
    if not isinstance(response, dict) or response.get("status") == "success":
        return False
    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        code = remarks.get("error_code") or ""
        message = (remarks.get("error_message") or "").lower()
    else:
        code = ""
        message = str(remarks or "").lower()
    return code in {"DH-1111", "DH-1112"} or "no holding" in message or "no position" in message or "no data" in message


def check(response: dict[str, Any], default: type[BrokerKitError] = BrokerKitError) -> Any:
    """Success -> return the unwrapped `data`. Failure -> raise (auth codes
    as AuthenticationError, everything else as `default`).

    `default`: domain exception when the code isn't auth-related (caller
    decides — e.g. OrderError from the order provider), same role as the
    `default` arg in Groww's `groww_errors` / Fyers' `check`.
    """
    if not isinstance(response, dict):
        raise default(f"Unexpected Dhan response (not a dict): {response!r}")
    if response.get("status") == "success":
        return response.get("data")

    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        code = remarks.get("error_code")
        message = remarks.get("error_message") or remarks.get("error_type")
    else:
        code = None
        message = str(remarks) if remarks else None

    if not message:
        # Nothing useful extracted — surface the whole envelope so the real
        # error is visible instead of a bare "Dhan API error". Dhan's error
        # bodies don't always use errorCode/errorType/errorMessage.
        message = f"Dhan API error; raw={response!r}"

    if code in _AUTH_CODES:
        raise AuthenticationError(f"[{code}] {message}")
    raise default(f"[{code}] {message}" if code else message)
