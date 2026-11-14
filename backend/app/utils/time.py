from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.utils.security import utc_now


def business_now() -> datetime:
    return utc_now().astimezone(ZoneInfo(get_settings().business_timezone))


def business_today() -> date:
    return business_now().date()
