from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.schemas.realtime import StockRtDailySnapshotResponse
from src.foundation.realtime import RealtimeSnapshotReader, RealtimeStateStore


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_STOCK_RT_DAILY_QUERY_CODES = 200


class RealtimeQueryValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RealtimeStockRtDailyQueryService:
    def __init__(
        self,
        *,
        store: RealtimeStateStore,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._reader = RealtimeSnapshotReader(
            store=store,
            now_provider=now_provider or (lambda: datetime.now(CN_TIMEZONE)),
        )

    def build_snapshot(self, session: Session, *, ts_codes: str | None) -> StockRtDailySnapshotResponse:
        normalized_codes = _normalize_ts_codes(ts_codes)
        if not normalized_codes:
            raise RealtimeQueryValidationError("MISSING_TS_CODES", "请提供需要查询的股票代码")
        if len(normalized_codes) > MAX_STOCK_RT_DAILY_QUERY_CODES:
            raise RealtimeQueryValidationError(
                "TOO_MANY_TS_CODES",
                f"单次最多查询 {MAX_STOCK_RT_DAILY_QUERY_CODES} 个股票代码",
            )

        result = self._reader.read_stock_rt_daily_snapshot(session, ts_codes=normalized_codes)
        return StockRtDailySnapshotResponse.model_validate(result.to_payload())


def _normalize_ts_codes(raw_value: str | None) -> list[str]:
    if raw_value is None:
        return []
    seen: set[str] = set()
    results: list[str] = []
    for part in raw_value.split(","):
        code = part.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        results.append(code)
    return results
