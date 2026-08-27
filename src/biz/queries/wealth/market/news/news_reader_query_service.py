from __future__ import annotations

import html
import re

from sqlalchemy.orm import Session

from src.biz.schemas.wealth.market.news_common import NewsContentSourceValue
from src.biz.schemas.wealth.market.news_reader import NewsReaderItemDto
from src.biz.services.wealth.market.news.news_reader_content_resolver import (
    NewsReaderContentEmptyError,
    resolve_major_news_reader_content,
    resolve_news_reader_content,
)

from .major_news_reader_query import MajorNewsReaderQuery
from .news_display_title import build_news_display_title
from .news_reader_query import NewsReaderQuery


class NewsReaderNotFoundError(LookupError):
    pass


class NewsReaderQueryService:
    def __init__(self) -> None:
        self._news_query = NewsReaderQuery()
        self._major_news_query = MajorNewsReaderQuery()

    def build_news_reader_item(
        self,
        session: Session,
        *,
        content_source: NewsContentSourceValue,
        news_id: str,
    ) -> NewsReaderItemDto:
        if content_source == "news":
            row = self._news_query.load_by_id(session, news_id=news_id)
        elif content_source == "major_news":
            row = self._major_news_query.load_by_id(session, news_id=news_id)
        else:
            raise AssertionError(f"unsupported news content source: {content_source}")
        if row is None:
            raise NewsReaderNotFoundError("news item was not found")

        try:
            resolved = (
                resolve_news_reader_content(row.content)
                if content_source == "news"
                else resolve_major_news_reader_content(row.content, source=row.source)
            )
        except NewsReaderContentEmptyError as exc:
            raise NewsReaderNotFoundError("news content is unavailable") from exc

        if content_source == "news":
            title = build_news_display_title(
                row.title,
                _build_content_title(row.content or ""),
            )
        else:
            title = (row.title or "").strip()
        if not title:
            raise NewsReaderNotFoundError("news title is unavailable")

        return NewsReaderItemDto(
            newsId=row.news_id,
            contentSource=content_source,
            title=title,
            source=row.source,
            publishTime=row.publish_time,
            readerMode=resolved.mode,
            url=resolved.url,
            html=resolved.html,
            content=resolved.content,
            originalUrl=((row.original_url or "").strip() or None) if content_source == "major_news" else None,
        )


def _build_content_title(content: str) -> str:
    without_tags = re.sub(r"(?is)<[^>]+>", " ", content)
    normalized = " ".join(html.unescape(without_tags).split())
    return normalized[:80]
