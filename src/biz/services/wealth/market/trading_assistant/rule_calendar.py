"""Calendar-backed A-share complete-minute windows (design §4.34).

Gold 1m keeps the 09:30 auction row as a cumulative-volume contribution;
regular complete-minute checkpoints are 09:31–11:30 and 13:01–15:00.
No weekday inference or synthetic zero-volume bars.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .rule_minute_batch import RequiredMinute


BEIJING = ZoneInfo("Asia/Shanghai")
TIME_LABEL_VERSION = "CN_A_GOLD_1M_END_WITH_AUCTION_V1"


def session_minutes(day):
    opening = datetime.combine(day, time(9, 30), tzinfo=BEIJING)
    afternoon = datetime.combine(day, time(13), tzinfo=BEIJING)
    return (RequiredMinute(opening, False),
        *(RequiredMinute(opening + timedelta(minutes=i), True) for i in range(1, 121)),
        *(RequiredMinute(afternoon + timedelta(minutes=i), True) for i in range(1, 121)))


def has_future_checkpoint(market, session, security, after, through, deadline):
    after, through = after.astimezone(BEIJING), through.astimezone(BEIJING)
    if through <= after:
        return False
    start = after.date()
    while start <= through.date():
        end = min(through.date(), start + timedelta(days=market.policy.page_rows - 1))
        basis = market.read_calendar(session, security.exchange, start, end, deadline)
        for day in basis.days:
            if day.is_open and any(m.is_checkpoint and after < m.at <= through for m in session_minutes(day.trade_date)):
                return True
        start = end + timedelta(days=1)
        deadline.remaining_ms()
    return False
