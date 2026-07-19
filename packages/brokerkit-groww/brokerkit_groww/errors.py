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

# Groww exception -> core exception (subclass order matters: specific pehle)
_MAP: list[tuple[type[BaseGrowwException], type[BrokerKitError]]] = [
    (GrowwAPIAuthenticationException, AuthenticationError),
    (GrowwAPIAuthorisationException, AuthenticationError),
    (InstrumentNotFoundException, InstrumentNotFoundError),
    (GrowwFeedConnectionException, StreamingConnectionError),
    (GrowwFeedNotSubscribedException, NotSubscribedError),
]


@contextmanager
def groww_errors(default: type[BrokerKitError] = BrokerKitError) -> Iterator[None]:
    """SDK calls ko wrap karo; growwapi exceptions core exceptions ban jaati hain.

    `default`: jo Groww error _MAP mein nahi hai wo is core type mein jayega —
    caller apna domain batata hai (e.g. orders provider `OrderError` pass karega).
    """
    try:
        yield
    except BaseGrowwException as e:
        for groww_type, core_type in _MAP:
            if isinstance(e, groww_type):
                raise core_type(e.msg) from e
        raise default(e.msg) from e
