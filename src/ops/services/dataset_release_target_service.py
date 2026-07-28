from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.datasets.source_release_policies import (
    NEXT_CALENDAR_DAY_0830_RELEASE,
    SAME_DAY_RELEASE,
)


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
KPL_LIST_RELEASE_TIME = time(8, 30)


@dataclass(frozen=True, slots=True)
class DatasetReleaseTarget:
    target_trade_date: date | None
    is_resolved: bool
    reason: str | None = None


class DatasetReleaseTargetService:
    """Derive a source-ready business date from dataset facts and the SSE calendar."""

    def resolve(
        self,
        *,
        definition: DatasetDefinition,
        now: datetime,
        open_trade_dates: list[date],
    ) -> DatasetReleaseTarget:
        local_now = self._as_business_time(now)
        candidates = sorted({value for value in open_trade_dates if value <= local_now.date()})
        if not candidates:
            return DatasetReleaseTarget(None, False, "交易日历缺少可用开市日")

        if definition.source.release_policy == SAME_DAY_RELEASE:
            return DatasetReleaseTarget(candidates[-1], True)

        if definition.source.release_policy == NEXT_CALENDAR_DAY_0830_RELEASE:
            # A date can only be ready after its following calendar-day release time.
            for candidate in reversed(candidates):
                release_at = datetime.combine(
                    candidate + timedelta(days=1),
                    KPL_LIST_RELEASE_TIME,
                    tzinfo=BUSINESS_TIMEZONE,
                )
                if local_now >= release_at:
                    return DatasetReleaseTarget(candidate, True)
            return DatasetReleaseTarget(None, False, "尚无已到源端发布时间的开市日")

        return DatasetReleaseTarget(None, False, f"不支持的源端发布策略：{definition.source.release_policy}")

    @staticmethod
    def _as_business_time(now: datetime) -> datetime:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
        return now.astimezone(BUSINESS_TIMEZONE)
