from brokerkit.exceptions.common import BrokerKitError

class InstrumentNotFoundError(BrokerKitError):
    """Raised when an instrument is not found."""