"""Authentication and session errors."""

from brokerkit.exceptions.common import BrokerKitError


class AuthenticationError(BrokerKitError):
    """Login failed, or the session is not valid for this call.

    Raised for bad or missing credentials, a rejected token, and a session
    the broker has invalidated.

    Note that a broker refusing a call for lack of a *subscription* is not
    this error, even though it often arrives as the same HTTP 403. Those
    surface as the caller's own domain error, because the session is fine and
    pointing the user at their credentials would send them to debug the wrong
    thing.
    """


class TokenExpiredError(AuthenticationError):
    """The access token has passed its expiry.

    A subclass of :class:`AuthenticationError`, so catching that catches this
    too. Providers normally refresh before this can surface; it is mostly of
    interest when a token was supplied by hand.
    """
