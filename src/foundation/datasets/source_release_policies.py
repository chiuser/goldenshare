from __future__ import annotations


SAME_DAY_RELEASE = "same_day"
NEXT_CALENDAR_DAY_0830_RELEASE = "next_calendar_day_0830"

SUPPORTED_SOURCE_RELEASE_POLICIES = frozenset(
    {
        SAME_DAY_RELEASE,
        NEXT_CALENDAR_DAY_0830_RELEASE,
    }
)
