from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.biz.schemas.realtime import StockRtDailySnapshotItem, StockRtDailySnapshotResponse
from src.foundation.realtime import (
    RealtimeFeedUnavailable,
    RealtimeMarketClock,
    RealtimeStateStore,
    RealtimeStateStoreUnavailable,
    get_realtime_stock_rt_daily_config,
)


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
        self._store = store
        self._now_provider = now_provider or (lambda: datetime.now(CN_TIMEZONE))

    def build_snapshot(self, session: Session, *, ts_codes: str | None) -> StockRtDailySnapshotResponse:
        config = get_realtime_stock_rt_daily_config(session)
        normalized_codes = _normalize_ts_codes(ts_codes)
        if not normalized_codes:
            raise RealtimeQueryValidationError("MISSING_TS_CODES", "请提供需要查询的股票代码")
        if len(normalized_codes) > MAX_STOCK_RT_DAILY_QUERY_CODES:
            raise RealtimeQueryValidationError(
                "TOO_MANY_TS_CODES",
                f"单次最多查询 {MAX_STOCK_RT_DAILY_QUERY_CODES} 个股票代码",
            )

        try:
            batch_id = self._store.get_current_batch_id(config.feed_key)
            if not batch_id:
                raise RealtimeFeedUnavailable("实时行情流尚未发布可读批次")
            meta = self._store.get_batch_meta(config.feed_key, batch_id)
            if meta is None:
                raise RealtimeFeedUnavailable("实时行情流当前批次缺少元信息")
            snapshots_by_code = self._store.get_snapshots(config.feed_key, batch_id, normalized_codes)
        except RealtimeStateStoreUnavailable:
            raise

        now = self._now_provider().astimezone(CN_TIMEZONE)
        clock = RealtimeMarketClock().resolve(
            session,
            exchange=config.exchange,
            collection_sessions=config.collection_sessions,
            now=now,
        )
        age_seconds = _age_seconds(meta.get("published_at"), now)
        stale = (
            clock.collection_status == "open"
            and age_seconds is not None
            and age_seconds > config.stale_after_seconds
        )
        items = [
            StockRtDailySnapshotItem.model_validate(snapshots_by_code[code])
            for code in normalized_codes
            if code in snapshots_by_code
        ]
        return StockRtDailySnapshotResponse(
            feed_key=config.feed_key,
            batch_id=batch_id,
            received_at=_string_or_none(meta.get("received_at")),
            published_at=_string_or_none(meta.get("published_at")),
            stale=stale,
            stale_after_seconds=config.stale_after_seconds,
            collection_status=clock.collection_status,
            items=items,
            missing_ts_codes=[code for code in normalized_codes if code not in snapshots_by_code],
        )


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


def _age_seconds(raw_value: object, now: datetime) -> float | None:
    if raw_value is None:
        return None
    try:
        published_at = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - published_at.astimezone(CN_TIMEZONE)).total_seconds())


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)
