from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.core_serving.news_stock_link import NewsStockLink


class NewsStockLinkDAO(BaseDAO[NewsStockLink]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, NewsStockLink)

    def existing_keys_by_news_ids(self, news_ids: Iterable[str]) -> set[tuple[str, str]]:
        ids = tuple(dict.fromkeys(news_id for news_id in news_ids if news_id))
        if not ids:
            return set()
        statement = select(NewsStockLink.news_id, NewsStockLink.ts_code).where(NewsStockLink.news_id.in_(ids))
        return {(str(news_id), str(ts_code)) for news_id, ts_code in self.session.execute(statement)}

    def existing_records_by_news_ids(self, news_ids: Iterable[str]) -> dict[tuple[str, str], datetime]:
        ids = tuple(dict.fromkeys(news_id for news_id in news_ids if news_id))
        if not ids:
            return {}
        statement = select(
            NewsStockLink.news_id,
            NewsStockLink.ts_code,
            NewsStockLink.created_at,
        ).where(NewsStockLink.news_id.in_(ids))
        return {
            (str(news_id), str(ts_code)): created_at
            for news_id, ts_code, created_at in self.session.execute(statement)
        }

    def delete_by_news_ids(self, news_ids: Iterable[str]) -> int:
        ids = tuple(dict.fromkeys(news_id for news_id in news_ids if news_id))
        if not ids:
            return 0
        result = self.session.execute(delete(NewsStockLink).where(NewsStockLink.news_id.in_(ids)))
        return int(result.rowcount or 0)

    def delete_by_keys(self, keys: Iterable[tuple[str, str]]) -> int:
        normalized = tuple(dict.fromkeys((news_id, ts_code) for news_id, ts_code in keys if news_id and ts_code))
        if not normalized:
            return 0
        deleted = 0
        for news_id, ts_code in normalized:
            result = self.session.execute(
                delete(NewsStockLink).where(
                    NewsStockLink.news_id == news_id,
                    NewsStockLink.ts_code == ts_code,
                )
            )
            deleted += int(result.rowcount or 0)
        return deleted

    def bulk_upsert_current(self, rows: list[dict[str, object]]) -> int:
        batch_created_at = datetime.now(timezone.utc)
        normalized_rows = [
            {
                **row,
                "created_at": row.get("created_at") or batch_created_at,
            }
            for row in rows
        ]
        return self.bulk_upsert(normalized_rows, conflict_columns=["news_id", "ts_code"])
