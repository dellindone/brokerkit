from contextlib import contextmanager
from typing import Iterator

from kiteconnect import exceptions as kite_ex

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.exceptions.order import OrderError

# Kite is the best-behaved SDK in this project on errors: `_request` inspects
# the response body and RAISES a typed exception (TokenException,
# OrderException, ...) for every API-level failure. That's the opposite of
# Fyers ({"s": "error"}), Dhan (failure envelope) and Angel (`status: false`,
# merely logged) — all three of which needed an inspect-the-envelope helper
# because they never raise. Here a plain context manager is enough; there is
# no `check()` counterpart and no envelope to unwrap, since the SDK also
# already returns `data` unwrapped.


@contextmanager
def zerodha_errors(default: type[BrokerKitError] = BrokerKitError) -> Iterator[None]:
    """Translate kiteconnect exceptions into core ones.

    `TokenException` -> AuthenticationError (the session really is bad).

    `PermissionException` is deliberately NOT an auth error, despite both
    being 403s. Live-verified 2026-07-21: on a free Personal-plan app, every
    market-data and historical call returns `PermissionException:
    "Insufficient permission for that call."` while portfolio and orders
    work perfectly — so the session is valid and only the *subscription* is
    missing. Mapping it to AuthenticationError told the user their login had
    failed when it hadn't, sending them to debug the wrong thing entirely.
    It now surfaces as the caller's own domain error with the real cause
    spelled out.

    `OrderException` -> OrderError regardless of the caller's domain (Kite
    raises it only from order calls). Everything else -> `default`.
    """
    try:
        yield
    except kite_ex.TokenException as e:
        raise AuthenticationError(str(e)) from e
    except kite_ex.PermissionException as e:
        raise default(
            f"{e} — this usually means the Kite Connect plan doesn't cover "
            f"this call. Market data, historical candles and streaming need "
            f"the paid Connect plan; the free Personal plan covers only "
            f"orders, GTT, portfolio and margins."
        ) from e
    except kite_ex.OrderException as e:
        raise OrderError(str(e)) from e
    except kite_ex.KiteException as e:
        raise default(str(e)) from e
