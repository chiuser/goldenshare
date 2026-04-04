from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.ops.index_series_active import IndexSeriesActive


class IndexSeriesActiveDAO(BaseDAO[IndexSeriesActive]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, IndexSeriesActive)

    def list_active_codes(self, resource: str) -> list[str]:
        stmt = (
            select(IndexSeriesActive.ts_code)
            .where(IndexSeriesActive.resource == resource)
            .order_by(IndexSeriesActive.ts_code)
        )
        return list(self.session.scalars(stmt))

    def upsert_seen_codes(self, resource: str, latest_seen_by_code: dict[str, date], checked_at: datetime | None = None) -> int:
        if not latest_seen_by_code:
            return 0
        observed_at = checked_at or datetime.now(timezone.utc)
        rows = [
            {
                "resource": resource,
                "ts_code": ts_code,
                "first_seen_date": seen_date,
                "last_seen_date": seen_date,
                "last_checked_at": observed_at,
            }
            for ts_code, seen_date in latest_seen_by_code.items()
        ]
        statement = insert(IndexSeriesActive).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["resource", "ts_code"],
            set_={
                "first_seen_date": func.least(IndexSeriesActive.first_seen_date, statement.excluded.first_seen_date),
                "last_seen_date": func.greatest(IndexSeriesActive.last_seen_date, statement.excluded.last_seen_date),
                "last_checked_at": statement.excluded.last_checked_at,
                "updated_at": func.now(),
            },
        )
        result = self.session.execute(statement)
        return result.rowcount or len(rows)
