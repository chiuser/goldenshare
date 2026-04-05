from __future__ import annotations

from datetime import date


class BuildFactorSnapshotService:
    def build_cursor(self, ts_code: str, trade_date: date) -> str:
        return f"{ts_code}:{trade_date.isoformat()}"
