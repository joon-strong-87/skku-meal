"""Calendar date used by all Korean campus menu requests."""
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def korean_today(now=None):
    """Return the Korean date; injected instants must be timezone-aware."""
    if now is None:
        now = datetime.now(KST)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(KST).date()
