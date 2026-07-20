from typing import Any, Iterator

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.factory import create_broker
from brokerkit.exceptions.common import BrokerKitError


class BrokerManager:
    """Named, multi-account collection of Broker instances.

    Har Broker instance already isolated hai (instance-scoped state —
    apna client, apne providers), isliye alag accounts already independent
    chalte hain. Ye class sirf convenience layer hai: account_id -> Broker.
    """

    def __init__(self) -> None:
        self._brokers: dict[str, Broker] = {}

    async def add(self, account_id: str, broker_name: str, **config: Any) -> Broker:
        if account_id in self._brokers:
            raise BrokerKitError(f"account {account_id!r} already added")
        broker = await create_broker(broker_name, **config)
        self._brokers[account_id] = broker
        return broker

    def get(self, account_id: str) -> Broker:
        try:
            return self._brokers[account_id]
        except KeyError:
            raise BrokerKitError(f"no account {account_id!r}") from None

    def __getitem__(self, account_id: str) -> Broker:
        return self.get(account_id)

    def __iter__(self) -> Iterator[tuple[str, Broker]]:
        return iter(self._brokers.items())

    def __len__(self) -> int:
        return len(self._brokers)

    async def remove(self, account_id: str) -> None:
        broker = self.get(account_id)
        await broker.close()
        del self._brokers[account_id]

    async def close_all(self) -> None:
        for broker in self._brokers.values():
            await broker.close()
        self._brokers.clear()
