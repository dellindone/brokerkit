"""Timezone helpers.

Every timestamp in BrokerKit is IST, the timezone Indian exchanges operate
in, so datetimes are made timezone-aware in :data:`IST` rather than left
naive.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
"""Indian Standard Time -- the timezone for all timestamps in this framework."""


def next_occurrence(at: time, now: datetime | None = None) -> datetime:
    """Return the next IST datetime at which the clock reads ``at``.

    Today if that time is still ahead, otherwise tomorrow. Used to schedule
    against fixed daily boundaries, such as the 6:00 AM IST token expiry that
    Groww and Zerodha share.
    """
    now = now or datetime.now(IST)
    candidate = datetime.combine(now.date(), at, tzinfo=IST)
    if now < candidate:
        return candidate
    return candidate + timedelta(days=1)
