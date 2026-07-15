from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from brokerkit.utils.datetime import IST

EXPIRY_SAFETY_BUFFER = timedelta(minutes=2)

class AuthToken(BaseModel):
    token: str
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(IST) >= self.expires_at - EXPIRY_SAFETY_BUFFER
    