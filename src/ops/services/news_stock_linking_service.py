from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

from src.foundation.config.settings import get_settings
from src.foundation.dao.news_stock_link_dao import NewsStockLinkDAO
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving_light.namechange import NamechangeLight
from src.foundation.models.core_serving_light.news import NewsLight
from src.foundation.news_linking import (
    HistoricalNameEntry,
    NewsRecord,
    StockLexiconEntry,
    StockNewsLink,
    StockNewsLinker,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
NEWS_STOCK_LINKING_ACTION_KEY = "maintenance.materialize_news_stock_links"
NEWS_STOCK_RULE_VERSION = "news-stock-rule-v1"
DEFAULT_OVERLAP_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class NewsStockLinkingStats:
    rows_fetched: int = 0
    matched_news_count: int = 0
    links_inserted: int = 0
    links_updated: int = 0
    links_deleted: int = 0
    rows_deduplicated: int = 0
    unmatched_news_count: int = 0
    batch_count: int = 0
    last_cursor: dict[str, str] | None = None
    overlap_seconds: int = 0
    invalid_dictionary_rows: int = 0

    @property
    def rows_saved(self) -> int:
        return self.links_inserted + self.links_updated

    def as_diagnostics(self) -> dict[str, Any]:
        return {
            "matched_news_count": self.matched_news_count,
            "links_inserted": self.links_inserted,
            "links_updated": self.links_updated,
            "links_deleted": self.links_deleted,
            "rows_deduplicated": self.rows_deduplicated,
            "unmatched_news_count": self.unmatched_news_count,
            "overlap_seconds": self.overlap_seconds,
            "batch_count": self.batch_count,
            "last_cursor": self.last_cursor,
            "invalid_dictionary_rows": self.invalid_dictionary_rows,
        }


class NewsStockLinkingService:
    """Materialize deterministic links from the news view into core_serving."""

    def __init__(self, *, session_factory: Callable[[], Any], batch_size: int | None = None) -> None:
        self._session_factory = session_factory
        self._batch_size = max(int(batch_size or get_settings().sync_batch_size), 1)

    def materialize(
        self,
        *,
        window_start: datetime | None,
        window_end: datetime,
        overlap_seconds: int = 0,
        rule_version: str = NEWS_STOCK_RULE_VERSION,
    ) -> NewsStockLinkingStats:
        start = _ensure_aware(window_start) if window_start is not None else None
        end = _ensure_aware(window_end)
        if start is not None and start >= end:
            raise ValueError("news linking window_start must be before window_end")

        entries, historical_names, invalid_dictionary_rows = self._load_lexicon()
        linker = StockNewsLinker(entries, historical_names=historical_names, rule_version=rule_version)
        stats = NewsStockLinkingStats(
            overlap_seconds=max(int(overlap_seconds), 0),
            invalid_dictionary_rows=invalid_dictionary_rows,
        )
        cursor: tuple[datetime, str] | None = None

        with self._session_factory() as read_session:
            while True:
                rows = self._fetch_news_batch(
                    read_session,
                    window_start=start,
                    window_end=end,
                    cursor=cursor,
                )
                if not rows:
                    break

                links_by_news_id: dict[str, list[StockNewsLink]] = {}
                raw_link_count = 0
                for row in rows:
                    news_id = str(row.row_key_hash)
                    news_date = _news_date(row.news_time)
                    links = linker.link(
                        NewsRecord(
                            news_id=news_id,
                            title=row.title,
                            content=row.content,
                            news_date=news_date,
                        )
                    )
                    raw_link_count += len(links)
                    links_by_news_id[news_id] = list(links)

                batch_stats = self._materialize_batch(
                    links_by_news_id=links_by_news_id,
                    linker_links=tuple(link for links in links_by_news_id.values() for link in links),
                )
                stats = NewsStockLinkingStats(
                    rows_fetched=stats.rows_fetched + len(rows),
                    matched_news_count=stats.matched_news_count + batch_stats["matched_news_count"],
                    links_inserted=stats.links_inserted + batch_stats["links_inserted"],
                    links_updated=stats.links_updated + batch_stats["links_updated"],
                    links_deleted=stats.links_deleted + batch_stats["links_deleted"],
                    rows_deduplicated=stats.rows_deduplicated + max(raw_link_count - batch_stats["current_link_count"], 0),
                    unmatched_news_count=stats.unmatched_news_count + batch_stats["unmatched_news_count"],
                    batch_count=stats.batch_count + 1,
                    last_cursor={
                        "fetched_at": _ensure_aware(rows[-1].fetched_at).isoformat(),
                        "row_key_hash": str(rows[-1].row_key_hash),
                    },
                    overlap_seconds=stats.overlap_seconds,
                    invalid_dictionary_rows=stats.invalid_dictionary_rows,
                )
                cursor = (_ensure_aware(rows[-1].fetched_at), str(rows[-1].row_key_hash))

        return stats

    def _load_lexicon(self) -> tuple[tuple[StockLexiconEntry, ...], tuple[HistoricalNameEntry, ...], int]:
        with self._session_factory() as session:
            securities = tuple(
                session.scalars(
                    select(Security)
                    .where(Security.security_type == "EQUITY")
                    .order_by(Security.ts_code.asc())
                )
            )
            entries = tuple(
                StockLexiconEntry(
                    ts_code=security.ts_code,
                    symbol=security.symbol,
                    name=security.name,
                    fullname=security.fullname,
                    security_type=security.security_type,
                )
                for security in securities
            )
            ts_codes = {entry.ts_code.upper() for entry in entries}
            history_rows = tuple(
                session.scalars(
                    select(NamechangeLight)
                    .where(NamechangeLight.ts_code.in_(ts_codes))
                    .order_by(
                        NamechangeLight.ts_code.asc(),
                        NamechangeLight.start_date.asc(),
                        NamechangeLight.row_key_hash.asc(),
                    )
                )
            )

        historical_names: list[HistoricalNameEntry] = []
        invalid_rows = 0
        for row in history_rows:
            if row.end_date is not None and row.end_date < row.start_date:
                invalid_rows += 1
                continue
            if not row.name.strip():
                invalid_rows += 1
                continue
            historical_names.append(
                HistoricalNameEntry(
                    ts_code=row.ts_code,
                    name=row.name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                )
            )
        return entries, tuple(historical_names), invalid_rows

    def _fetch_news_batch(
        self,
        session: Any,
        *,
        window_start: datetime | None,
        window_end: datetime,
        cursor: tuple[datetime, str] | None,
    ) -> tuple[NewsLight, ...]:
        conditions = [NewsLight.fetched_at < window_end]
        if window_start is not None:
            conditions.append(NewsLight.fetched_at >= window_start)
        if cursor is not None:
            cursor_fetched_at, cursor_news_id = cursor
            conditions.append(
                or_(
                    NewsLight.fetched_at > cursor_fetched_at,
                    and_(NewsLight.fetched_at == cursor_fetched_at, NewsLight.row_key_hash > cursor_news_id),
                )
            )
        statement = (
            select(NewsLight)
            .where(and_(*conditions))
            .order_by(NewsLight.fetched_at.asc(), NewsLight.row_key_hash.asc())
            .limit(self._batch_size)
        )
        return tuple(session.scalars(statement))

    def _materialize_batch(
        self,
        *,
        links_by_news_id: dict[str, list[StockNewsLink]],
        linker_links: tuple[StockNewsLink, ...],
    ) -> dict[str, int]:
        current_rows: list[dict[str, object]] = []
        current_keys: set[tuple[str, str]] = set()
        with self._session_factory() as session:
            dao = NewsStockLinkDAO(session)
            existing_records = dao.existing_records_by_news_ids(links_by_news_id.keys())
            for link in linker_links:
                key = (link.news_id, link.ts_code)
                if key in current_keys:
                    continue
                current_keys.add(key)
                row: dict[str, object] = {
                    "news_id": link.news_id,
                    "ts_code": link.ts_code,
                    "match_method": link.match_method.value,
                    "source_field": link.source_field.value,
                    "rule_version": link.rule_version,
                }
                if key in existing_records:
                    row["created_at"] = existing_records[key]
                current_rows.append(row)

            news_ids = tuple(links_by_news_id)
            existing_keys = set(existing_records)
            deleted = dao.delete_by_news_ids(news_ids)
            inserted = len(current_keys - existing_keys)
            updated = len(current_keys & existing_keys)
            if current_rows:
                dao.bulk_upsert_current(current_rows)
            session.commit()

        return {
            "matched_news_count": sum(bool(links) for links in links_by_news_id.values()),
            "links_inserted": inserted,
            "links_updated": updated,
            "links_deleted": len(existing_keys - current_keys) if deleted else 0,
            "unmatched_news_count": sum(not links for links in links_by_news_id.values()),
            "current_link_count": len(current_keys),
        }


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _news_date(value: datetime) -> date:
    return _ensure_aware(value).astimezone(SHANGHAI).date()
