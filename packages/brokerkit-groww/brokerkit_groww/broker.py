from growwapi import GrowwAPI

from brokerkit_groww.auth import GrowwAuth
from brokerkit_groww.instruments import GrowwInstruments
from brokerkit_groww.order import GrowwOrderProvider
from brokerkit_groww.portfolio import GrowwPortfolio
from brokerkit_groww.market import GrowwMarketData
from brokerkit_groww.historical import GrowwHistorical

class GrowwBroker:
    def __init__(self, totp_key: str, totp_secret: str):
        self.auth = GrowwAuth(totp_key=totp_key, totp_secret=totp_secret)
        self.instruments = None
        self._client = None
        self.orders = None
        self.portfolio = None
        self.market = None
        self.historical = None

    @classmethod
    async def create(cls, totp_key: str, totp_secret: str):
        broker = cls(totp_key=totp_key, totp_secret=totp_secret)
        token = await broker.auth.get_token()
        broker._client = GrowwAPI(token.token)
        broker.instruments = GrowwInstruments(client=broker._client)
        broker.orders = GrowwOrderProvider(client=broker._client)
        broker.portfolio = GrowwPortfolio(client=broker._client)
        broker.market = GrowwMarketData(client=broker._client)
        broker.historical = GrowwHistorical(client=broker._client)
        return broker
    