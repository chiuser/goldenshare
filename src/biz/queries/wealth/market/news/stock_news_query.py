from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving_light.news import NewsLight

from .market_news_query import NewsQueryResult, NewsQueryRow, _build_display_title, _day_start, _has_displayable_text, _to_date


class StockNewsQuery:
    """Load stock news rows from company-channel news."""

    def load_rows(
        self,
        session: Session,
        *,
        trade_date: date,
        limit: int,
    ) -> NewsQueryResult:
        rows = session.execute(
            select(
                NewsLight.row_key_hash,
                NewsLight.news_time,
                NewsLight.title,
                NewsLight.content,
                NewsLight.src,
            )
            .where(
                NewsLight.news_time >= _day_start(trade_date),
                NewsLight.news_time < _day_start(trade_date + timedelta(days=1)),
                NewsLight.channels == "公司",
                _has_displayable_text(),
            )
            .order_by(NewsLight.news_time.desc(), NewsLight.row_key_hash.asc())
            .limit(limit)
        ).all()
        observed = self.load_observed_trade_date(session)
        return NewsQueryResult(
            rows=[
                NewsQueryRow(
                    news_id=row.row_key_hash,
                    publish_time=row.news_time,
                    title=_build_display_title(title=row.title, content=row.content),
                    source=row.src,
                )
                for row in rows
            ],
            observed_trade_date=observed,
        )

    def load_observed_trade_date(self, session: Session) -> date | None:
        observed_at = session.scalar(
            select(func.max(NewsLight.news_time)).where(
                NewsLight.channels == "公司",
                _has_displayable_text(),
            )
        )
        return _to_date(observed_at)
