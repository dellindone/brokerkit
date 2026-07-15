from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def next_occurrence(at: time, now: datetime | None = None) -> datetime:
    now = now or datetime.now(IST)
    candidate = datetime.combine(now.date(), at, tzinfo=IST)
    if now < candidate: return candidate
    return candidate + timedelta(days=1)
