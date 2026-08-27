from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.news.major_news_display_policy import MAJOR_NEWS_EXCLUDED_SOURCE
from src.foundation.models.core_serving_light.major_news import MajorNewsLight


@dataclass(frozen=True, slots=True)
class MajorNewsReaderQueryRow:
    news_id: str
    publish_time: datetime
    title: str | None
    source: str
    content: str | None
    original_url: str | None


class MajorNewsReaderQuery:
    def load_by_id(self, session: Session, *, news_id: str) -> MajorNewsReaderQueryRow | None:
        row = session.execute(
            select(
                MajorNewsLight.row_key_hash,
                MajorNewsLight.pub_time,
                MajorNewsLight.title,
                MajorNewsLight.src,
                MajorNewsLight.content,
                MajorNewsLight.url,
            )
            .where(
                MajorNewsLight.row_key_hash == news_id,
                func.trim(MajorNewsLight.src) != MAJOR_NEWS_EXCLUDED_SOURCE,
            )
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return MajorNewsReaderQueryRow(
            news_id=row.row_key_hash,
            publish_time=row.pub_time,
            title=row.title,
            source=row.src,
            content=row.content,
            original_url=row.url,
        )
