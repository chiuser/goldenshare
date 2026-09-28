from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.biz.services.wealth.news_intelligence.contracts import (
    FrozenNewsItem,
    NewsSourceType,
    ReplayWindow,
)
from src.biz.services.wealth.news_intelligence.replay import freeze_news_item
from src.foundation.models.core_serving_light.cctv_news import CctvNewsLight
from src.foundation.models.core_serving_light.major_news import MajorNewsLight
from src.foundation.models.core_serving_light.news import NewsLight


_READ_ONLY_TRANSACTION_INFO_KEY = "news_intelligence_m1_read_only_transaction"


def ensure_repeatable_read_only_transaction(session: Session) -> None:
    """Set the PostgreSQL snapshot before the first source query in a transaction."""
    if session.get_bind().dialect.name != "postgresql":
        return
    current_transaction = session.get_transaction()
    if (
        current_transaction is not None
        and session.info.get(_READ_ONLY_TRANSACTION_INFO_KEY) is current_transaction
    ):
        return
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    session.info[_READ_ONLY_TRANSACTION_INFO_KEY] = session.get_transaction()


class NewsIntelligenceReplaySourceQuery:
    """Stream a frozen historical-business-time snapshot without reading legacy score."""

    def __init__(self, *, batch_size: int = 500) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._batch_size = batch_size

    def stream_timed_window(
        self, session: Session, *, window: ReplayWindow
    ) -> Iterator[FrozenNewsItem]:
        ensure_repeatable_read_only_transaction(session)
        news_statement = (
            select(
                NewsLight.row_key_hash,
                NewsLight.title,
                NewsLight.content,
                NewsLight.src,
                NewsLight.news_time,
                NewsLight.fetched_at,
            )
            .where(
                NewsLight.news_time >= window.start_at,
                NewsLight.news_time < window.end_at,
            )
            .order_by(NewsLight.news_time, NewsLight.row_key_hash)
            .execution_options(yield_per=self._batch_size, stream_results=True)
        )
        for row in session.execute(news_statement):
            yield freeze_news_item(
                source_type=NewsSourceType.NEWS,
                source_key=row.row_key_hash,
                title=row.title,
                content=row.content,
                source_name=row.src,
                published_at=row.news_time,
                content_date=None,
                fetched_at=row.fetched_at,
                replay_assignment=window.window_kind,
            )

        major_statement = (
            select(
                MajorNewsLight.row_key_hash,
                MajorNewsLight.title,
                MajorNewsLight.content,
                MajorNewsLight.src,
                MajorNewsLight.pub_time,
                MajorNewsLight.fetched_at,
            )
            .where(
                MajorNewsLight.pub_time >= window.start_at,
                MajorNewsLight.pub_time < window.end_at,
            )
            .order_by(MajorNewsLight.pub_time, MajorNewsLight.row_key_hash)
            .execution_options(yield_per=self._batch_size, stream_results=True)
        )
        for row in session.execute(major_statement):
            yield freeze_news_item(
                source_type=NewsSourceType.MAJOR_NEWS,
                source_key=row.row_key_hash,
                title=row.title,
                content=row.content,
                source_name=row.src,
                published_at=row.pub_time,
                content_date=None,
                fetched_at=row.fetched_at,
                replay_assignment=window.window_kind,
            )

    def stream_cctv_date(
        self, session: Session, *, content_date: date
    ) -> Iterator[FrozenNewsItem]:
        ensure_repeatable_read_only_transaction(session)
        statement = (
            select(
                CctvNewsLight.row_key_hash,
                CctvNewsLight.title,
                CctvNewsLight.content,
                CctvNewsLight.source,
                CctvNewsLight.date,
                CctvNewsLight.fetched_at,
            )
            .where(CctvNewsLight.date == content_date)
            .order_by(CctvNewsLight.row_key_hash)
            .execution_options(yield_per=self._batch_size, stream_results=True)
        )
        for row in session.execute(statement):
            yield freeze_news_item(
                source_type=NewsSourceType.CCTV_NEWS,
                source_key=row.row_key_hash,
                title=row.title,
                content=row.content,
                source_name=row.source,
                published_at=None,
                content_date=row.date,
                fetched_at=row.fetched_at,
                replay_assignment="CCTV_DATE_COHORT",
            )
