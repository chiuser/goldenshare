from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.schemas.realtime import StockRtMinSnapshotResponse
from src.foundation.realtime import RealtimeSnapshotReader, RealtimeStateStore, normalize_stock_rt_min_freq


CN_TIMEZONE = ZoneInfo("Asia/Shanghai")
MAX_STOCK_RT_MIN_QUERY_CODES = 200


class RealtimeStockRtMinQueryValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RealtimeStockRtMinQueryService:
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

    def build_snapshot(self, session: Session, *, freq: str | None, ts_codes: str | None) -> StockRtMinSnapshotResponse:
        normalized_freq = _normalize_freq(freq)
        normalized_codes = _normalize_ts_codes(ts_codes)
        if not normalized_codes:
            raise RealtimeStockRtMinQueryValidationError("MISSING_TS_CODES", "请提供需要查询的股票代码")
        if len(normalized_codes) > MAX_STOCK_RT_MIN_QUERY_CODES:
            raise RealtimeStockRtMinQueryValidationError(
                "TOO_MANY_TS_CODES",
                f"单次最多查询 {MAX_STOCK_RT_MIN_QUERY_CODES} 个股票代码",
            )
        if any("*" in code for code in normalized_codes):
            raise RealtimeStockRtMinQueryValidationError("UNSUPPORTED_TS_CODE_PATTERN", "实时分钟查询不接受通配符股票代码")

        result = self._reader.read_stock_rt_min_snapshot(session, freq=normalized_freq, ts_codes=normalized_codes)
        return StockRtMinSnapshotResponse.model_validate(result.to_payload())


def _normalize_freq(raw_value: str | None) -> str:
    if raw_value is None or not str(raw_value).strip():
        raise RealtimeStockRtMinQueryValidationError("MISSING_FREQ", "请提供实时分钟频率")
    try:
        return normalize_stock_rt_min_freq(raw_value)
    except ValueError as exc:
        raise RealtimeStockRtMinQueryValidationError("INVALID_FREQ", "实时分钟频率无效") from exc


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
