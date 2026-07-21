from datetime import datetime

from pydantic import BaseModel


class NewsArticle(BaseModel):
    instrument_key: str  # Upstox news response is keyed by instrument; carried onto each article
    heading: str
    summary: str
    thumbnail: str | None = None
    article_link: str
    published_time: datetime
