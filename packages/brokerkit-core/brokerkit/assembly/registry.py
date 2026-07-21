"""The broker name registry.

Maps a broker name (``"zerodha"``) to its
:class:`~brokerkit.assembly.broker.Broker` subclass. A subclass registers
itself on import via ``__init_subclass__``, so core never needs to import any
adapter -- the adapter registers itself when
:func:`~brokerkit.assembly.factory.create_broker` imports it.
"""

from typing import TYPE_CHECKING

from brokerkit.exceptions.common import BrokerKitError

if TYPE_CHECKING:
    from brokerkit.assembly.broker import Broker

_REGISTRY: dict[str, type["Broker"]] = {}


def register_broker(name: str, cls: type["Broker"]) -> None:
    """Record ``cls`` as the broker named ``name`` (case-insensitive)."""
    _REGISTRY[name.lower()] = cls


def get_broker_class(name: str) -> type["Broker"]:
    """Return the registered class for ``name``.

    Raises :class:`~brokerkit.exceptions.common.BrokerKitError`, listing what
    is registered, if the name is unknown. Note this does not trigger plugin
    discovery -- use :func:`~brokerkit.assembly.factory.create_broker` for
    that.
    """
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        raise BrokerKitError(
            f"No broker registered as {name!r}. "
            f"Registered: {sorted(_REGISTRY) or 'none'}"
        ) from None


def registered_brokers() -> list[str]:
    """Return the names of all currently registered brokers, sorted.

    Only brokers whose package has been imported appear here.
    """
    return sorted(_REGISTRY)
