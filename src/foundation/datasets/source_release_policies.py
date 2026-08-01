from __future__ import annotations


SAME_DAY_RELEASE = "same_day"
NEXT_CALENDAR_DAY_0830_RELEASE = "next_calendar_day_0830"
NEXT_OPEN_DAY_0930_RELEASE = "next_open_day_0930"

SUPPORTED_SOURCE_RELEASE_POLICIES = frozenset(
    {
        SAME_DAY_RELEASE,
        NEXT_CALENDAR_DAY_0830_RELEASE,
        NEXT_OPEN_DAY_0930_RELEASE,
    }
)
