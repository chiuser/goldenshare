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

    def record_execution_outcome(
        self,
        job_name: str,
        target_table: str,
        *,
        run_type: str,
        run_profile: str | None = None,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
        rows_committed: int | None = None,
    ) -> None:
        _ = (run_profile, rows_committed)
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
                    last_success_date = COALESCE(EXCLUDED.last_success_date, ops.sync_job_state.last_success_date),
                    last_success_at = EXCLUDED.last_success_at,
                    last_cursor = EXCLUDED.last_cursor,
                    full_sync_done = ops.sync_job_state.full_sync_done OR EXCLUDED.full_sync_done
                """
            ),
            {
                "job_name": job_name,
                "target_table": target_table,
                "last_success_date": last_success_date,
                "last_success_at": datetime.now(timezone.utc),
                "last_cursor": last_cursor,
                "full_sync_done": bool(run_type == "FULL" and last_success_date is None),
            },
        )
