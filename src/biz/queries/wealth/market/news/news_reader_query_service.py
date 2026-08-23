from __future__ import annotations

import html
import re

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.news_reader import NewsReaderItemDto
from src.biz.services.wealth.market.news.news_reader_content_resolver import (
    NewsReaderContentEmptyError,
    resolve_news_reader_content,
)

from .news_reader_query import NewsReaderQuery


class NewsReaderNotFoundError(LookupError):
    pass


class NewsReaderQueryService:
    def __init__(self) -> None:
        self._query = NewsReaderQuery()

    def build_news_reader_item(self, session: Session, *, news_id: str) -> NewsReaderItemDto:
        row = self._query.load_by_id(session, news_id=news_id)
        if row is None:
            raise NewsReaderNotFoundError("news item was not found")

        try:
            resolved = resolve_news_reader_content(row.content)
        except NewsReaderContentEmptyError as exc:
            raise NewsReaderNotFoundError("news content is unavailable") from exc

        title = (row.title or "").strip() or _build_content_title(row.content or "")
        if not title:
            raise NewsReaderNotFoundError("news title is unavailable")

        return NewsReaderItemDto(
            newsId=row.news_id,
            title=title,
            source=row.source,
            publishTime=row.publish_time,
            readerMode=resolved.mode,
            url=resolved.url,
            html=resolved.html,
            content=resolved.content,
        )


def _build_content_title(content: str) -> str:
    without_tags = re.sub(r"(?is)<[^>]+>", " ", content)
    normalized = " ".join(html.unescape(without_tags).split())
    return normalized[:80]
