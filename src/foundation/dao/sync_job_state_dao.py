from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


class SyncJobStateDAO:
    """历史兼容 DAO：不再依赖 ops ORM，直接写 ops.sync_job_state。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_last_success_date(self, job_name: str) -> date | None:
        return self.session.execute(
            text(
                """
                SELECT last_success_date
                FROM ops.sync_job_state
                WHERE job_name = :job_name
                """
            ),
            {"job_name": job_name},
        ).scalar_one_or_none()

    def mark_success(
        self,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None:
        self.session.execute(
            text(
                """
                INSERT INTO ops.sync_job_state (
                    job_name,
                    target_table,
                    last_success_date,
                    last_success_at,
                    last_cursor,
                    full_sync_done
                ) VALUES (
                    :job_name,
                    :target_table,
                    :last_success_date,
                    :last_success_at,
                    :last_cursor,
                    false
                )
                ON CONFLICT (job_name) DO UPDATE
                SET target_table = EXCLUDED.target_table,
                    last_success_date = EXCLUDED.last_success_date,
                    last_success_at = EXCLUDED.last_success_at,
                    last_cursor = EXCLUDED.last_cursor,
                    full_sync_done = ops.sync_job_state.full_sync_done
                """
            ),
            {
                "job_name": job_name,
                "target_table": target_table,
                "last_success_date": last_success_date,
                "last_success_at": datetime.now(timezone.utc),
                "last_cursor": last_cursor,
            },
        )

    def reconcile_success_date(self, job_name: str, target_table: str, last_success_date: date) -> None:
        state = self.session.execute(
            text(
                """
                SELECT last_success_at, last_cursor, full_sync_done
                FROM ops.sync_job_state
                WHERE job_name = :job_name
                """
            ),
            {"job_name": job_name},
        ).mappings().one_or_none()

        self.session.execute(
            text(
                """
                INSERT INTO ops.sync_job_state (
                    job_name,
                    target_table,
                    last_success_date,
                    last_success_at,
                    last_cursor,
                    full_sync_done
                ) VALUES (
                    :job_name,
                    :target_table,
                    :last_success_date,
                    :last_success_at,
                    :last_cursor,
                    :full_sync_done
                )
                ON CONFLICT (job_name) DO UPDATE
                SET target_table = EXCLUDED.target_table,
                    last_success_date = EXCLUDED.last_success_date,
                    last_success_at = EXCLUDED.last_success_at,
                    last_cursor = EXCLUDED.last_cursor,
                    full_sync_done = EXCLUDED.full_sync_done
                """
            ),
            {
                "job_name": job_name,
                "target_table": target_table,
                "last_success_date": last_success_date,
                "last_success_at": state["last_success_at"] if state is not None else datetime.now(timezone.utc),
                "last_cursor": state["last_cursor"] if state is not None else None,
                "full_sync_done": bool(state["full_sync_done"]) if state is not None else False,
            },
        )

    def mark_full_sync_done(self, job_name: str, target_table: str) -> None:
        self.session.execute(
            text(
                """
                INSERT INTO ops.sync_job_state (
                    job_name,
                    target_table,
                    last_success_date,
                    last_success_at,
                    last_cursor,
                    full_sync_done
                ) VALUES (
                    :job_name,
                    :target_table,
                    NULL,
                    :last_success_at,
                    NULL,
                    true
                )
                ON CONFLICT (job_name) DO UPDATE
                SET target_table = EXCLUDED.target_table,
                    last_success_date = EXCLUDED.last_success_date,
                    last_success_at = EXCLUDED.last_success_at,
                    last_cursor = EXCLUDED.last_cursor,
                    full_sync_done = EXCLUDED.full_sync_done
                """
            ),
            {
                "job_name": job_name,
                "target_table": target_table,
                "last_success_at": datetime.now(timezone.utc),
            },
        )
