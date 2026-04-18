from __future__ import annotations

from datetime import date, datetime
from typing import Protocol


class IndexSeriesActiveStore(Protocol):
    """活动指数池访问能力 contract。"""

    def list_active_codes(self, resource: str) -> list[str]:
        """按资源返回已激活指数代码。"""

    def upsert_seen_codes(
        self,
        resource: str,
        latest_seen_by_code: dict[str, date],
        checked_at: datetime | None = None,
    ) -> int:
        """按观测日期写回活动指数池。"""
