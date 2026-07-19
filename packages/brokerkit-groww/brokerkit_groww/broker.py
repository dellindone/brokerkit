from growwapi import GrowwAPI

from brokerkit_groww.auth import GrowwAuth
from brokerkit_groww.instruments import GrowwInstruments
from brokerkit_groww.order import GrowwOrderProvider
from brokerkit_groww.portfolio import GrowwPortfolio
class GrowwBroker:
    def __init__(self, totp_key: str, totp_secret: str):
        self.auth = GrowwAuth(totp_key=totp_key, totp_secret=totp_secret)
        self.instruments = None
        self._client = None
        self.orders = None
        self.portfolio = None

    @classmethod
    async def create(cls, totp_key: str, totp_secret: str):
        broker = cls(totp_key=totp_key, totp_secret=totp_secret)
        token = await broker.auth.get_token()
        broker._client = GrowwAPI(token.token)
        broker.instruments = GrowwInstruments(client=broker._client)
        broker.orders = GrowwOrderProvider(client=broker._client)
        broker.portfolio = GrowwPortfolio(client=broker._client)
        return broker
    