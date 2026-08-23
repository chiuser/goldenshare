from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

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

        statement = (
            select(NewsLight, NewsStockLink.match_method)
            .join(
                NewsStockLink,
                NewsStockLink.news_id == NewsLight.row_key_hash,
            )
            .where(NewsStockLink.ts_code == normalized_ts_code)
            .where(NewsLight.news_time >= resolved_start)
            .where(NewsLight.news_time < resolved_end)
            .order_by(NewsLight.news_time.desc(), NewsLight.row_key_hash.asc())
            .limit(effective_limit)
        )
        rows = session.execute(statement).all()
        items = [
            self._to_item(news, str(match_method), debug=debug)
            for news, match_method in rows
        ]
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
    def _to_item(news: NewsLight, match_method: str, *, debug: bool) -> StockDetailNewsItemDto:
        title = (news.title or "").strip()
        if not title:
            title = (news.content or "").strip()[:80]
        publish_time = _to_shanghai(news.news_time)
        return StockDetailNewsItemDto(
            newsId=str(news.row_key_hash),
            publishTime=publish_time,
            title=title,
            debugInfo=StockDetailNewsDebugInfoDto(matchMethod=match_method) if debug else None,
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
