import asyncio
import sys
import types

import pytest

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.broker_manager import BrokerManager
from brokerkit.assembly.factory import _resolve, create_broker
from brokerkit.assembly.registry import get_broker_class, registered_brokers
from brokerkit.exceptions import BrokerKitError


class DemoBroker(Broker):
    name = "test-demo"

    @classmethod
    async def create(cls, **config):
        instance = cls()
        instance.config = config
        instance.streaming = None
        return instance


def test_broker_subclass_registers_itself():
    assert get_broker_class("TEST-DEMO") is DemoBroker
    assert "test-demo" in registered_brokers()


def test_create_broker_delegates_config_to_registered_class():
    broker = asyncio.run(create_broker("test-demo", account="one"))
    assert isinstance(broker, DemoBroker)
    assert broker.config == {"account": "one"}


def test_factory_lazily_imports_and_registers_adapter(monkeypatch):
    module = types.ModuleType("brokerkit_fake")

    class FakeBroker(Broker):
        name = "fake"

        @classmethod
        async def create(cls, **config):
            return cls()

    module.FakeBroker = FakeBroker
    monkeypatch.setitem(sys.modules, "brokerkit_fake", module)
    assert _resolve("fake") is FakeBroker


def test_factory_explains_missing_adapter():
    with pytest.raises(BrokerKitError, match="brokerkit-definitely-not-real"):
        _resolve("definitely-not-real")


class ClosableBroker:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def test_broker_manager_get_remove_and_close_all():
    manager = BrokerManager()
    one, two = ClosableBroker(), ClosableBroker()
    manager._brokers = {"one": one, "two": two}

    assert manager["one"] is one
    asyncio.run(manager.remove("one"))
    assert one.closed and len(manager) == 1
    asyncio.run(manager.close_all())
    assert two.closed and len(manager) == 0


def test_broker_manager_rejects_unknown_account():
    with pytest.raises(BrokerKitError, match="no account"):
        BrokerManager().get("missing")
