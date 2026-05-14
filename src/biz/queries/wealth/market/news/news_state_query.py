from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


NEWS_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class NewsWindowContext:
    market: str
    window_start_at: datetime
    window_end_at: datetime
    as_of_time: datetime


class NewsStateQuery:
    """Resolve the natural-time news query window for market news panels."""

    def resolve_news_window(self, *, market: str) -> NewsWindowContext:
        now = datetime.now(NEWS_TIMEZONE)
        yesterday = now.date() - timedelta(days=1)
        window_start_at = datetime.combine(yesterday, time.min, tzinfo=NEWS_TIMEZONE)
        return NewsWindowContext(
            market=market,
            window_start_at=window_start_at,
            window_end_at=now,
            as_of_time=now,
        )
