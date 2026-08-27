from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.news.news_reader_content_resolver import NEWS_READER_HTML_PATTERN
from src.biz.services.wealth.market.news.major_news_display_policy import MAJOR_NEWS_EXCLUDED_SOURCE
from src.foundation.models.core_serving_light.major_news import MajorNewsLight

from .market_news_query import NewsQueryResult, NewsQueryRow


class MajorNewsQuery:
    """Load long-form communications from the serving-light major news outlet."""

    def load_rows(
        self,
        session: Session,
        *,
        window_start_at: datetime,
        window_end_at: datetime,
        limit: int,
    ) -> NewsQueryResult:
        display_title = func.trim(MajorNewsLight.title)
        normalized_content = func.trim(MajorNewsLight.content)
        reader_mode = case(
            (normalized_content.regexp_match(NEWS_READER_HTML_PATTERN), literal("HTML")),
            else_=literal("TEXT"),
        )
        deduped = (
            select(
                MajorNewsLight.row_key_hash.label("row_key_hash"),
                MajorNewsLight.pub_time.label("pub_time"),
                display_title.label("display_title"),
                MajorNewsLight.src.label("src"),
                reader_mode.label("reader_mode"),
                func.row_number()
                .over(
                    partition_by=display_title,
                    order_by=(MajorNewsLight.pub_time.desc(), MajorNewsLight.row_key_hash.asc()),
                )
                .label("content_rank"),
            )
            .where(
                MajorNewsLight.pub_time >= window_start_at,
                MajorNewsLight.pub_time <= window_end_at,
                func.trim(MajorNewsLight.src) != MAJOR_NEWS_EXCLUDED_SOURCE,
                func.length(display_title) > 0,
                func.length(normalized_content) > 0,
            )
            .subquery()
        )
        rows = session.execute(
            select(
                deduped.c.row_key_hash,
                deduped.c.pub_time,
                deduped.c.display_title,
                deduped.c.src,
                deduped.c.reader_mode,
            )
            .where(deduped.c.content_rank == 1)
            .order_by(deduped.c.pub_time.desc(), deduped.c.row_key_hash.asc())
            .limit(limit)
        ).all()
        return NewsQueryResult(
            rows=[
                NewsQueryRow(
                    news_id=row.row_key_hash,
                    publish_time=row.pub_time,
                    title=row.display_title,
                    source=row.src,
                    content_source="major_news",
                    reader_mode=row.reader_mode,
                )
                for row in rows
            ],
            observed_at=self.load_observed_at(session),
        )

    def load_observed_at(self, session: Session) -> datetime | None:
        return session.scalar(
            select(func.max(MajorNewsLight.pub_time)).where(
                func.trim(MajorNewsLight.src) != MAJOR_NEWS_EXCLUDED_SOURCE,
                func.length(func.trim(MajorNewsLight.title)) > 0,
                func.length(func.trim(MajorNewsLight.content)) > 0,
            )
        )
