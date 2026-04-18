from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


class IndexSeriesActiveDAO:
    """历史兼容 DAO：不再依赖 ops ORM，直接访问 ops.index_series_active。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active_codes(self, resource: str) -> list[str]:
        rows = self.session.execute(
            text(
                """
                SELECT ts_code
                FROM ops.index_series_active
                WHERE resource = :resource
                ORDER BY ts_code
                """
            ),
            {"resource": resource},
        ).all()
        return [row[0] for row in rows]

    def upsert_seen_codes(
        self,
        resource: str,
        latest_seen_by_code: dict[str, date],
        checked_at: datetime | None = None,
    ) -> int:
        if not latest_seen_by_code:
            return 0
        observed_at = checked_at or datetime.now(timezone.utc)
        rows = [
            {
                "resource": resource,
                "ts_code": ts_code,
                "seen_date": seen_date,
                "last_checked_at": observed_at,
            }
            for ts_code, seen_date in latest_seen_by_code.items()
        ]
        result = self.session.execute(
            text(
                """
                INSERT INTO ops.index_series_active (
                    resource,
                    ts_code,
                    first_seen_date,
                    last_seen_date,
                    last_checked_at
                ) VALUES (
                    :resource,
                    :ts_code,
                    :seen_date,
                    :seen_date,
                    :last_checked_at
                )
                ON CONFLICT (resource, ts_code) DO UPDATE
                SET first_seen_date = LEAST(
                        ops.index_series_active.first_seen_date,
                        EXCLUDED.first_seen_date
                    ),
                    last_seen_date = GREATEST(
                        ops.index_series_active.last_seen_date,
                        EXCLUDED.last_seen_date
                    ),
                    last_checked_at = EXCLUDED.last_checked_at,
                    updated_at = NOW()
                """
            ),
            rows,
        )
        return result.rowcount or len(rows)
