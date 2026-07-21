"""Base exception for the whole framework."""


class BrokerKitError(Exception):
    """Base class for every error BrokerKit raises.

    Adapters translate their vendor SDK's failures into this hierarchy, so
    application code can catch ``BrokerKitError`` and handle any broker
    uniformly instead of importing six different SDKs' exception types.

    Translation is not always a matter of catching: several vendor SDKs never
    raise at all and report failures in the response body instead, so
    adapters inspect as well as catch.
    """
