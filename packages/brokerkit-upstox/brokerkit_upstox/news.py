import asyncio
from typing import Any

from upstox_client import ApiClient, Configuration, NewsApi

from brokerkit.exceptions.common import BrokerKitError
from brokerkit.interfaces.auth import AuthProvider
from brokerkit.interfaces.news import NewsProvider
from brokerkit.models.instrument import Instrument
from brokerkit.models.news import NewsArticle

from brokerkit_upstox.errors import upstox_errors
from brokerkit_upstox.mapper import epoch_ms_dt, upstox_key

# Verified from the docs: max 30 instrument_keys per call, last 7 days of
# articles only.
_MAX_INSTRUMENT_KEYS = 30


class UpstoxNews(NewsProvider):
    """The other half of the reason this adapter exists, alongside
    fundamentals.py. Works with either token type (Analytics Token covers
    News per Upstox's docs). `positions`/`holdings` categories are resolved
    server-side against the authenticated account — no PortfolioProvider
    dependency needed here, verified from the docs' own wording ("no
    instrument_keys parameter required").
    """

    def __init__(self, auth: AuthProvider, configuration: Configuration):
        self._auth = auth
        self._configuration = configuration
        self._client = NewsApi(ApiClient(configuration))

    async def _refresh_token(self) -> None:
        token = await self._auth.get_token()
        self._configuration.access_token = token.token

    async def get_news(self, instruments: list[Instrument]) -> list[NewsArticle]:
        if len(instruments) > _MAX_INSTRUMENT_KEYS:
            raise BrokerKitError(
                f"Upstox news supports at most {_MAX_INSTRUMENT_KEYS} instruments per call, got {len(instruments)}"
            )
        keys = ",".join(upstox_key(i) for i in instruments)
        return await self._fetch("instrument_keys", instrument_keys=keys)

    async def get_news_for_positions(self) -> list[NewsArticle]:
        return await self._fetch("positions")

    async def get_news_for_holdings(self) -> list[NewsArticle]:
        return await self._fetch("holdings")

    async def _fetch(self, category: str, **kwargs: Any) -> list[NewsArticle]:
        await self._refresh_token()
        with upstox_errors():
            resp = await asyncio.to_thread(self._client.get_news, category, **kwargs)
        data = resp.to_dict().get("data") or {}
        out: list[NewsArticle] = []
        for instrument_key, articles in data.items():
            for a in articles or []:
                out.append(NewsArticle(
                    instrument_key=instrument_key,
                    heading=a["heading"],
                    summary=a["summary"],
                    thumbnail=a.get("thumbnail"),
                    article_link=a["article_link"],
                    published_time=epoch_ms_dt(a["published_time"]),
                ))
        return out
