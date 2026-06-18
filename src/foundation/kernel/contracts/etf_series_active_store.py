from __future__ import annotations

from datetime import date, datetime
from typing import Protocol


class EtfSeriesActiveStore(Protocol):
    """ETF 活跃池访问能力 contract。"""

    def list_active_codes(self, resource: str) -> list[str]:
        """按资源返回已激活 ETF 代码。"""

    def upsert_seen_codes(
        self,
        resource: str,
        latest_seen_by_code: dict[str, date],
        checked_at: datetime | None = None,
    ) -> int:
        """按观测日期写回 ETF 活跃池。"""
