"""A named collection of broker accounts."""

from typing import Any, Iterator

from brokerkit.assembly.broker import Broker
from brokerkit.assembly.factory import create_broker
from brokerkit.exceptions.common import BrokerKitError


class BrokerManager:
    """Holds several broker accounts under string ids.

    Each :class:`~brokerkit.assembly.broker.Broker` already keeps all its
    state on the instance -- its own client, its own providers -- so separate
    accounts are independent without any help. This class is just a
    convenience layer over that: a mapping from an account id to a broker,
    with lifecycle handling.

    A typical use is one live-trading account and one data account at once::

        manager = BrokerManager()
        await manager.add("main", "zerodha", api_key=..., api_secret=..., access_token=...)
        await manager.add("data", "fyers", client_id=..., secret_key=..., ...)
        quote = await manager["data"].market.get_quote(instrument)
        await manager.close_all()
    """

    def __init__(self) -> None:
        self._brokers: dict[str, Broker] = {}

    async def add(self, account_id: str, broker_name: str, **config: Any) -> Broker:
        """Create a broker and store it under ``account_id``.

        ``broker_name`` and ``config`` are passed straight to
        :func:`~brokerkit.assembly.factory.create_broker`. Raises
        :class:`~brokerkit.exceptions.common.BrokerKitError` if the id is
        already in use.
        """
        if account_id in self._brokers:
            raise BrokerKitError(f"account {account_id!r} already added")
        broker = await create_broker(broker_name, **config)
        self._brokers[account_id] = broker
        return broker

    def get(self, account_id: str) -> Broker:
        """Return the broker stored under ``account_id``.

        Raises :class:`~brokerkit.exceptions.common.BrokerKitError` if there
        is none. :meth:`__getitem__` (``manager[account_id]``) is equivalent.
        """
        try:
            return self._brokers[account_id]
        except KeyError:
            raise BrokerKitError(f"no account {account_id!r}") from None

    def __getitem__(self, account_id: str) -> Broker:
        """``manager[account_id]``; see :meth:`get`."""
        return self.get(account_id)

    def __iter__(self) -> Iterator[tuple[str, Broker]]:
        """Iterate over ``(account_id, broker)`` pairs."""
        return iter(self._brokers.items())

    def __len__(self) -> int:
        """Number of accounts held."""
        return len(self._brokers)

    async def remove(self, account_id: str) -> None:
        """Close the broker under ``account_id`` and drop it."""
        broker = self.get(account_id)
        await broker.close()
        del self._brokers[account_id]

    async def close_all(self) -> None:
        """Close every broker and empty the collection."""
        for broker in self._brokers.values():
            await broker.close()
        self._brokers.clear()
