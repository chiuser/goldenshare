from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving_light.news import NewsLight


@dataclass(frozen=True, slots=True)
class NewsQueryRow:
    news_id: str
    publish_time: datetime
    title: str
    source: str | None


@dataclass(frozen=True, slots=True)
class NewsQueryResult:
    rows: list[NewsQueryRow]
    observed_at: datetime | None


class MarketNewsQuery:
    """Load market news rows from the serving-light news outlet."""

    def load_rows(
        self,
        session: Session,
        *,
        window_start_at: datetime,
        window_end_at: datetime,
        limit: int,
    ) -> NewsQueryResult:
        display_title = _display_title_expr()
        deduped = (
            select(
                NewsLight.row_key_hash.label("row_key_hash"),
                NewsLight.news_time.label("news_time"),
                display_title.label("display_title"),
                NewsLight.src.label("src"),
                func.row_number()
                .over(
                    partition_by=display_title,
                    order_by=(NewsLight.news_time.desc(), NewsLight.row_key_hash.asc()),
                )
                .label("content_rank"),
            )
            .where(
                NewsLight.news_time >= window_start_at,
                NewsLight.news_time <= window_end_at,
                or_(NewsLight.channels.is_(None), NewsLight.channels != "公司"),
                _has_nonempty_content(),
            )
            .subquery()
        )
        rows = session.execute(
            select(
                deduped.c.row_key_hash,
                deduped.c.news_time,
                deduped.c.display_title,
                deduped.c.src,
            )
            .where(deduped.c.content_rank == 1)
            .order_by(deduped.c.news_time.desc(), deduped.c.row_key_hash.asc())
            .limit(limit)
        ).all()
        observed = self.load_observed_at(session)
        return NewsQueryResult(
            rows=[
                NewsQueryRow(
                    news_id=row.row_key_hash,
                    publish_time=row.news_time,
                    title=row.display_title,
                    source=row.src,
                )
                for row in rows
            ],
            observed_at=observed,
        )

    def load_observed_at(self, session: Session) -> datetime | None:
        observed_at = session.scalar(
            select(func.max(NewsLight.news_time)).where(
                or_(NewsLight.channels.is_(None), NewsLight.channels != "公司"),
                _has_nonempty_content(),
            )
        )
        return observed_at


def _has_nonempty_content():
    return func.length(func.trim(NewsLight.content)) > 0


def _display_title_expr():
    title_or_content = func.coalesce(func.nullif(func.trim(NewsLight.title), ""), func.trim(NewsLight.content))
    return func.substr(title_or_content, 1, 80)
