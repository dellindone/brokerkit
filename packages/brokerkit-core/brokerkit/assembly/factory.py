"""The create_broker factory and its plugin discovery."""

import importlib
from typing import Any

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.registry import get_broker_class
from brokerkit.exceptions.common import BrokerKitError


def _resolve(name: str) -> type[Broker]:
    """Return the Broker subclass for ``name``, importing its adapter if needed.

    If the name is not yet registered, the matching ``brokerkit_<name>``
    package is imported, which registers its Broker subclass as a side effect.
    This is what lets core stay independent of every adapter. Raises
    :class:`~brokerkit.exceptions.common.BrokerKitError` if no such package is
    installed.
    """
    try:
        return get_broker_class(name)
    except BrokerKitError:
        try:
            importlib.import_module(f"brokerkit_{name.lower()}")
        except ModuleNotFoundError as e:
            raise BrokerKitError(
                f"Unknown broker {name!r} -- is `brokerkit-{name.lower()}` installed?"
            ) from e
        return get_broker_class(name)


async def create_broker(name: str, **config: Any) -> Broker:
    """Authenticate with a broker by name and return a ready instance.

    Resolves ``name`` to its adapter (installing nothing, but importing the
    ``brokerkit_<name>`` package on first use) and calls its ``create`` with
    ``config``. The config keyword arguments are broker-specific; see each
    adapter\'s documentation.

    ::

        broker = await create_broker(
            "zerodha", api_key=..., api_secret=..., access_token=...
        )
    """
    cls = _resolve(name)
    return await cls.create(**config)
