from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


class EtfSeriesActiveDAO:
    """ETF 活跃池 DAO：不依赖 ops ORM，直接访问 ops.etf_series_active。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active_codes(self, resource: str) -> list[str]:
        rows = self.session.execute(
            text(
                """
                SELECT ts_code
                FROM ops.etf_series_active
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
                INSERT INTO ops.etf_series_active (
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
                SET first_seen_date = CASE
                        WHEN first_seen_date <= EXCLUDED.first_seen_date
                        THEN first_seen_date
                        ELSE EXCLUDED.first_seen_date
                    END,
                    last_seen_date = CASE
                        WHEN last_seen_date >= EXCLUDED.last_seen_date
                        THEN last_seen_date
                        ELSE EXCLUDED.last_seen_date
                    END,
                    last_checked_at = EXCLUDED.last_checked_at,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            rows,
        )
        return result.rowcount or len(rows)
