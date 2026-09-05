from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.news.news_event_deduplicator import (
    NEWS_EVENT_CANDIDATE_BATCH_SIZE,
    NEWS_EVENT_MAX_CANDIDATE_SCAN,
    NEWS_EVENT_WINDOW,
    NewsEvent,
    NewsEventCandidate,
    deduplicate_news_events,
)
from src.biz.queries.wealth.market.stock_detail.stock_detail_query_service import StockDetailNotFoundError
from src.biz.schemas.wealth.market.stock_detail import StockDetailStockRefDto
from src.biz.schemas.wealth.market.stock_detail_news import (
    StockDetailNewsDebugInfoDto,
    StockDetailNewsItemDto,
    StockDetailNewsMetaDto,
    StockDetailNewsResponseDto,
)
from src.foundation.models.core_serving.news_stock_link import NewsStockLink
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving_light.news import NewsLight


SHANGHAI = ZoneInfo("Asia/Shanghai")


class StockDetailNewsQuery:
    DEFAULT_LIMIT = 50
    MAX_LIMIT = 2000
    DEFAULT_MONTHS = 2

    def build(
        self,
        session: Session,
        *,
        ts_code: str,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        debug: bool,
    ) -> StockDetailNewsResponseDto:
        normalized_ts_code = ts_code.strip().upper()
        security = session.scalar(
            select(Security).where(
                Security.ts_code == normalized_ts_code,
                Security.security_type == "EQUITY",
            )
        )
        if security is None:
            raise StockDetailNotFoundError(f"未找到股票标的：{normalized_ts_code}")
        if limit < 1:
            raise ValueError("limit 必须大于等于 1")

        resolved_end = _to_shanghai(end_at) if end_at is not None else datetime.now(SHANGHAI)
        resolved_start = (
            _to_shanghai(start_at)
            if start_at is not None
            else _subtract_calendar_months(resolved_end, self.DEFAULT_MONTHS)
        )
        if resolved_start >= resolved_end:
            raise ValueError("startAt 必须早于 endAt")
        effective_limit = min(limit, self.MAX_LIMIT)

        candidates = self._load_candidates(
            session,
            ts_code=normalized_ts_code,
            start_at=resolved_start,
            end_at=resolved_end,
            limit=effective_limit,
        )
        events = deduplicate_news_events(candidates)[:effective_limit]
        items = [self._to_item(event, debug=debug) for event in events]
        return StockDetailNewsResponseDto(
            stockRef=StockDetailStockRefDto(tsCode=security.ts_code, name=security.name),
            items=items,
            meta=StockDetailNewsMetaDto(
                count=len(items),
                limit=effective_limit,
                startAt=resolved_start,
                endAt=resolved_end,
            ),
        )

    @staticmethod
    def _load_candidates(
        session: Session,
        *,
        ts_code: str,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> list[NewsEventCandidate]:
        candidates: list[NewsEventCandidate] = []
        cursor_time: datetime | None = None
        cursor_news_id: str | None = None

        while len(candidates) < NEWS_EVENT_MAX_CANDIDATE_SCAN:
            batch_limit = min(
                NEWS_EVENT_CANDIDATE_BATCH_SIZE,
                NEWS_EVENT_MAX_CANDIDATE_SCAN - len(candidates),
            )
            statement = (
                select(
                    NewsLight.row_key_hash,
                    NewsLight.news_time,
                    NewsLight.title,
                    NewsLight.content,
                    NewsLight.src,
                    NewsStockLink.match_method,
                )
                .join(
                    NewsStockLink,
                    NewsStockLink.news_id == NewsLight.row_key_hash,
                )
                .where(NewsStockLink.ts_code == ts_code)
                .where(NewsLight.news_time >= start_at)
                .where(NewsLight.news_time < end_at)
            )
            if cursor_time is not None and cursor_news_id is not None:
                statement = statement.where(
                    or_(
                        NewsLight.news_time < cursor_time,
                        and_(
                            NewsLight.news_time == cursor_time,
                            NewsLight.row_key_hash > cursor_news_id,
                        ),
                    )
                )
            statement = statement.order_by(
                NewsLight.news_time.desc(),
                NewsLight.row_key_hash.asc(),
            ).limit(batch_limit)

            rows = session.execute(statement).all()
            if not rows:
                break

            candidates.extend(
                NewsEventCandidate(
                    news_id=str(news_id),
                    publish_time=_to_shanghai(news_time),
                    title=title,
                    content=content,
                    source=str(source),
                    match_method=str(match_method),
                )
                for news_id, news_time, title, content, source, match_method in rows
            )

            events = deduplicate_news_events(candidates)
            if len(events) >= limit:
                merge_cutoff = events[limit - 1].representative.publish_time - NEWS_EVENT_WINDOW
                if candidates[-1].publish_time < merge_cutoff:
                    break

            if len(rows) < batch_limit:
                break
            cursor_news_id = str(rows[-1][0])
            cursor_time = rows[-1][1]

        return candidates

    @staticmethod
    def _to_item(event: NewsEvent, *, debug: bool) -> StockDetailNewsItemDto:
        representative = event.representative
        return StockDetailNewsItemDto(
            newsId=representative.news_id,
            publishTime=representative.publish_time,
            title=event.display_title,
            debugInfo=(
                StockDetailNewsDebugInfoDto(matchMethod=representative.match_method)
                if debug
                else None
            ),
        )


def _to_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI)


def _subtract_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + (value.month - 1) - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
