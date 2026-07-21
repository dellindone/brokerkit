"""Contract tests — written once, run against every adapter.

This is the point of M3: proving the ABC abstraction actually generalizes.
Rather than re-verifying the interface six times by hand, these assert the
same structural contract for each adapter: its ``Broker`` subclass is
registered and constructible, and none of its provider implementations has an
abstract hole. The individual mapper tests cover behaviour; this covers shape.
"""

import inspect

import pytest

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.registry import get_broker_class, registered_brokers
import brokerkit.interfaces as interfaces

from tests.support import ADAPTERS, import_adapter, iter_adapter_modules

# Every abstract provider base an adapter class might implement.
PROVIDER_ABCS = tuple(
    obj
    for name, obj in vars(interfaces).items()
    if isinstance(obj, type) and name.endswith("Provider")
)


def _broker_class(adapter: str) -> type[Broker]:
    package = import_adapter(adapter)
    subclasses = [
        obj
        for obj in vars(package).values()
        if isinstance(obj, type) and issubclass(obj, Broker) and obj is not Broker
    ]
    assert len(subclasses) == 1, f"{adapter}: expected exactly one Broker subclass, got {subclasses}"
    return subclasses[0]


def _provider_classes(adapter: str):
    seen: dict[str, type] = {}
    for module in iter_adapter_modules(adapter):
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, PROVIDER_ABCS)
                and obj not in PROVIDER_ABCS
                and obj.__module__.startswith(f"brokerkit_{adapter}")
            ):
                seen[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return list(seen.values())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_broker_is_named_and_registered(adapter):
    broker = _broker_class(adapter)
    assert isinstance(broker.name, str) and broker.name
    # Setting `name` auto-registers on import; the registry must resolve back.
    assert broker.name in registered_brokers()
    assert get_broker_class(broker.name) is broker


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_create_is_async_classmethod(adapter):
    broker = _broker_class(adapter)
    create = broker.__dict__.get("create")
    assert isinstance(create, classmethod), f"{adapter}: create must be a classmethod"
    assert inspect.iscoroutinefunction(broker.create), f"{adapter}: create must be async"


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_provider_implementations_have_no_abstract_holes(adapter):
    providers = _provider_classes(adapter)
    assert providers, f"{adapter}: no provider implementations found"
    unfinished = {cls.__qualname__: sorted(cls.__abstractmethods__) for cls in providers if inspect.isabstract(cls)}
    assert not unfinished, f"{adapter}: providers with unimplemented abstract methods: {unfinished}"


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_broker_wires_the_six_core_providers(adapter):
    """Broker declares six core provider attributes (instruments, orders,
    portfolio, market, historical, streaming). Each adapter must expose a
    concrete implementation of each ABC somewhere in its stack — otherwise a
    broker instance would be missing a provider it promises."""
    implemented = {
        base
        for cls in _provider_classes(adapter)
        for base in PROVIDER_ABCS
        if issubclass(cls, base)
    }
    core_required = {
        interfaces.InstrumentProvider,
        interfaces.OrderProvider,
        interfaces.PortfolioProvider,
        interfaces.MarketDataProvider,
        interfaces.HistoricalDataProvider,
        interfaces.StreamingProvider,
    }
    missing = core_required - implemented
    assert not missing, f"{adapter}: no implementation of {sorted(b.__name__ for b in missing)}"
