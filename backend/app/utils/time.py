from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.utils.security import utc_now


def business_now() -> datetime:
    now = utc_now()
    try:
        return now.astimezone(ZoneInfo(get_settings().business_timezone))
    except ZoneInfoNotFoundError:
        return now


def business_today() -> date:
    return business_now().date()
