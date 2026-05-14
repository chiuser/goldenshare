from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

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
    observed_trade_date: date | None


class MarketNewsQuery:
    """Load market news rows from the serving-light news outlet."""

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
                or_(NewsLight.channels.is_(None), NewsLight.channels != "公司"),
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
                or_(NewsLight.channels.is_(None), NewsLight.channels != "公司"),
                _has_displayable_text(),
            )
        )
        return _to_date(observed_at)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _has_displayable_text():
    return or_(
        func.length(func.trim(NewsLight.title)) > 0,
        func.length(func.trim(NewsLight.content)) > 0,
    )


def _build_display_title(*, title: str | None, content: str | None) -> str:
    text = (title or "").strip() or (content or "").strip()
    return text[:80]


def _to_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    return value.date()
