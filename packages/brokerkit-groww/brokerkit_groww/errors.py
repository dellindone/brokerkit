"""Groww error translation into core exceptions."""

from contextlib import contextmanager
from typing import Iterator

from growwapi.groww.exceptions import (
    BaseGrowwException,
    GrowwAPIAuthenticationException,
    GrowwAPIAuthorisationException,
    GrowwFeedConnectionException,
    GrowwFeedNotSubscribedException,
    InstrumentNotFoundException,
)

from brokerkit.exceptions.auth import AuthenticationError
from brokerkit.exceptions.common import BrokerKitError
from brokerkit.exceptions.instrument import InstrumentNotFoundError
from brokerkit.exceptions.streaming import (
    NotSubscribedError,
    StreamingConnectionError,
)

# Groww exception -> core exception (subclass order matters: most specific first)
_MAP: list[tuple[type[BaseGrowwException], type[BrokerKitError]]] = [
    (GrowwAPIAuthenticationException, AuthenticationError),
    (GrowwAPIAuthorisationException, AuthenticationError),
    (InstrumentNotFoundException, InstrumentNotFoundError),
    (GrowwFeedConnectionException, StreamingConnectionError),
    (GrowwFeedNotSubscribedException, NotSubscribedError),
]


@contextmanager
def groww_errors(default: type[BrokerKitError] = BrokerKitError) -> Iterator[None]:
    """Wrap SDK calls, translating growwapi exceptions into core ones.

    A Groww exception listed in ``_MAP`` becomes its mapped core type;
    anything else becomes ``default``, which the caller sets to its own domain
    error (the order provider passes
    :class:`~brokerkit.exceptions.order.OrderError`, for example).
    """
    try:
        yield
    except BaseGrowwException as e:
        for groww_type, core_type in _MAP:
            if isinstance(e, groww_type):
                raise core_type(e.msg) from e
        raise default(e.msg) from e
