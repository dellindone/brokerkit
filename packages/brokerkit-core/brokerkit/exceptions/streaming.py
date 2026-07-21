"""Live market feed errors."""

from brokerkit.exceptions.common import BrokerKitError


class StreamingError(BrokerKitError):
    """A streaming operation failed.

    Also raised for limitations an adapter can detect but not fix -- for
    example subscribing to an instrument whose broker token is missing, or a
    vendor feed class that cannot support two concurrent connections in one
    process.
    """


class StreamingConnectionError(StreamingError):
    """The websocket could not be established, or dropped.

    Raised when a connection fails to open within the adapter's timeout, or
    errors before it ever opened -- so a failed connect surfaces here instead
    of hanging a subscribe call forever.
    """


class NotSubscribedError(StreamingError):
    """An operation referenced an instrument that is not subscribed."""
