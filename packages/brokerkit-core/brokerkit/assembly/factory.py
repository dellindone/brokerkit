import importlib
from typing import Any

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.registry import get_broker_class
from brokerkit.exceptions.common import BrokerKitError


def _resolve(name: str) -> type[Broker]:
    try:
        return get_broker_class(name)
    except BrokerKitError:
        # Plugin discovery: brokerkit_<name> import karo — adapter ka
        # __init__ apna Broker subclass register kar deta hai
        try:
            importlib.import_module(f"brokerkit_{name.lower()}")
        except ModuleNotFoundError as e:
            raise BrokerKitError(
                f"Unknown broker {name!r} — is `brokerkit-{name.lower()}` installed?"
            ) from e
        return get_broker_class(name)


async def create_broker(name: str, **config: Any) -> Broker:
    """`create_broker("groww", totp_key=..., totp_secret=...)`"""
    cls = _resolve(name)
    return await cls.create(**config)
