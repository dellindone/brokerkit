"""Instrument lookup errors."""

from brokerkit.exceptions.common import BrokerKitError


class InstrumentNotFoundError(BrokerKitError):
    """No instrument matched the given identifiers."""
