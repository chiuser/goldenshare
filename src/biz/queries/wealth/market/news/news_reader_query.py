from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving_light.news import NewsLight


@dataclass(frozen=True, slots=True)
class NewsReaderQueryRow:
    news_id: str
    publish_time: datetime
    title: str | None
    source: str
    content: str | None


class NewsReaderQuery:
    def load_by_id(self, session: Session, *, news_id: str) -> NewsReaderQueryRow | None:
        row = session.execute(
            select(
                NewsLight.row_key_hash,
                NewsLight.news_time,
                NewsLight.title,
                NewsLight.src,
                NewsLight.content,
            )
            .where(NewsLight.row_key_hash == news_id)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return NewsReaderQueryRow(
            news_id=row.row_key_hash,
            publish_time=row.news_time,
            title=row.title,
            source=row.src,
            content=row.content,
        )
