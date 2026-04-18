from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils import truncate_text


@dataclass(slots=True, frozen=True)
class SyncRunLogHandle:
    id: int


class SyncRunLogDAO:
    """历史兼容 DAO：不再依赖 ops ORM，直接写 ops.sync_run_log。"""

    MAX_LOG_MESSAGE_LENGTH = 16_000

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_log(self, job_name: str, run_type: str, execution_id: int | None = None) -> SyncRunLogHandle:
        log_id = self.session.execute(
            text(
                """
                INSERT INTO ops.sync_run_log (
                    execution_id,
                    job_name,
                    run_type,
                    started_at,
                    status
                ) VALUES (
                    :execution_id,
                    :job_name,
                    :run_type,
                    :started_at,
                    :status
                )
                RETURNING id
                """
            ),
            {
                "execution_id": execution_id,
                "job_name": job_name,
                "run_type": run_type,
                "started_at": datetime.now(timezone.utc),
                "status": "RUNNING",
            },
        ).scalar_one()
        self.session.commit()
        return SyncRunLogHandle(id=int(log_id))

    def finish_log(
        self,
        log: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        if not isinstance(log, SyncRunLogHandle):
            raise TypeError("SyncRunLogDAO.finish_log expects SyncRunLogHandle")
        self.session.execute(
            text(
                """
                UPDATE ops.sync_run_log
                SET status = :status,
                    ended_at = :ended_at,
                    rows_fetched = :rows_fetched,
                    rows_written = :rows_written,
                    message = :message
                WHERE id = :id
                """
            ),
            {
                "id": log.id,
                "status": status,
                "ended_at": datetime.now(timezone.utc),
                "rows_fetched": rows_fetched,
                "rows_written": rows_written,
                "message": truncate_text(message, self.MAX_LOG_MESSAGE_LENGTH),
            },
        )
