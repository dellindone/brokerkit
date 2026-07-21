from typing import Any

from upstox_client import Configuration

from brokerkit.assembly.broker import Broker
from brokerkit.exceptions import AuthenticationError

from brokerkit_upstox.auth import UpstoxAnalyticsAuth, UpstoxOAuth
from brokerkit_upstox.charges import UpstoxCharges
from brokerkit_upstox.fundamentals import UpstoxFundamentals
from brokerkit_upstox.historical import UpstoxHistorical
from brokerkit_upstox.instruments import UpstoxInstruments
from brokerkit_upstox.market import UpstoxMarketData
from brokerkit_upstox.market_information import UpstoxMarketInformation
from brokerkit_upstox.news import UpstoxNews
from brokerkit_upstox.order import UpstoxOrderProvider
from brokerkit_upstox.portfolio import UpstoxPortfolio
from brokerkit_upstox.streaming import UpstoxStreaming


class UpstoxBroker(Broker):
    """Deliberately not a single-token adapter like Groww/Fyers — see
    ROADMAP Phase 10.2. `analytics_token` (dashboard-generated, 1-year,
    read-only, no static IP) powers market/historical/market_information/
    fundamentals/news with zero daily-login friction; `client_id`/`client_secret`/
    `redirect_uri` (official OAuth, browser-based — no headless refresh is
    possible, unlike Groww/Fyers) powers orders/portfolio. `access_token`
    is an escape hatch for an already-obtained OAuth token (see
    `UpstoxOAuth`'s docstring) — usable on its own for same-day testing,
    or alongside the three client credentials so it still refreshes via
    browser once it expires. At least one of analytics_token / access_token
    / the three client credentials must be given. Any subset gives a
    partially-wired broker —
    unset attributes fail loudly (AttributeError) on use, not silently —
    matching this adapter's actual purpose (fundamentals+news, not
    execution; see brokerkit-broker-strategy memory). Data-facing
    providers prefer the Analytics Token when both are given (simpler, no
    interactive refresh); only orders/portfolio ever use OAuth.

    `create()` does no eager network call (unlike Groww/Fyers, which
    log in immediately): constructing with only an analytics_token must
    stay instant and silent, since the fundamentals/news-only use case
    shouldn't be forced through a browser login it doesn't need. The OAuth
    browser flow only fires lazily, the first time something that actually
    needs it is called (via AuthProvider.get_token()'s inherited
    check-then-login behavior).
    """

    name = "upstox"

    def __init__(
        self,
        analytics_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        access_token: str | None = None,
    ):
        has_oauth_creds = bool(client_id and client_secret and redirect_uri)
        has_oauth = has_oauth_creds or bool(access_token)
        if not analytics_token and not has_oauth:
            raise AuthenticationError(
                "UpstoxBroker needs analytics_token and/or access_token and/or "
                "(client_id, client_secret, redirect_uri)"
            )
        oauth = (
            UpstoxOAuth(client_id, client_secret, redirect_uri, access_token=access_token)
            if has_oauth else None
        )
        data_auth = UpstoxAnalyticsAuth(analytics_token) if analytics_token else oauth

        self.instruments = UpstoxInstruments()
        data_configuration = Configuration()
        self.historical = UpstoxHistorical(data_configuration)  # no token needed at all (verified: auth_settings=[])
        self.market = UpstoxMarketData(data_auth, data_configuration)
        self.market_information = UpstoxMarketInformation(data_auth, data_configuration)
        self.charges = UpstoxCharges(data_auth, data_configuration)
        self.fundamentals = UpstoxFundamentals(data_auth, data_configuration)
        self.news = UpstoxNews(data_auth, data_configuration)
        self.streaming = UpstoxStreaming(data_configuration)

        if oauth is not None:
            write_configuration = Configuration()
            self.orders = UpstoxOrderProvider(oauth, write_configuration)
            self.portfolio = UpstoxPortfolio(oauth, write_configuration)

    @classmethod
    async def create(cls, **config: Any) -> "UpstoxBroker":
        return cls(**config)
