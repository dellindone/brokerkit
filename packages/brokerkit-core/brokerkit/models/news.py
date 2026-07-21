"""Market news model."""

from datetime import datetime

from pydantic import BaseModel


class NewsArticle(BaseModel):
    """A news article linked to an instrument.

    Returned by :class:`~brokerkit.interfaces.news.NewsProvider`.
    """

    instrument_key: str
    """The instrument this article was returned for. News responses are keyed
    by instrument, and that key is carried onto each article so a flat list
    of articles is still attributable."""

    heading: str
    summary: str
    thumbnail: str | None = None
    article_link: str
    published_time: datetime
