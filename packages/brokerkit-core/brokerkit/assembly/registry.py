from typing import TYPE_CHECKING

from brokerkit.exceptions.common import BrokerKitError

if TYPE_CHECKING:
    from brokerkit.assembly.broker import Broker

_REGISTRY: dict[str, type["Broker"]] = {}


def register_broker(name: str, cls: type["Broker"]) -> None:
    _REGISTRY[name.lower()] = cls


def get_broker_class(name: str) -> type["Broker"]:
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        raise BrokerKitError(
            f"No broker registered as {name!r}. "
            f"Registered: {sorted(_REGISTRY) or 'none'}"
        ) from None


def registered_brokers() -> list[str]:
    return sorted(_REGISTRY)
