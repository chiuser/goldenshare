from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from src.dao.base_dao import BaseDAO
from src.models.ops.sync_job_state import SyncJobState


class SyncJobStateDAO(BaseDAO[SyncJobState]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, SyncJobState)

    def get_last_success_date(self, job_name: str) -> date | None:
        state = self.fetch_by_pk(job_name)
        return state.last_success_date if state else None

    def mark_success(self, job_name: str, target_table: str, last_success_date: date | None = None, last_cursor: str | None = None) -> None:
        state = self.fetch_by_pk(job_name)
        row = {
            "job_name": job_name,
            "target_table": target_table,
            "last_success_date": last_success_date,
            "last_success_at": datetime.utcnow(),
            "last_cursor": last_cursor,
        }
        if state is None:
            row["full_sync_done"] = False
        self.bulk_upsert([row])

    def mark_full_sync_done(self, job_name: str, target_table: str) -> None:
        self.bulk_upsert(
            [
                {
                    "job_name": job_name,
                    "target_table": target_table,
                    "last_success_at": datetime.utcnow(),
                    "full_sync_done": True,
                }
            ]
        )
