from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunLogStore
from src.ops.models.ops.sync_job_state import SyncJobState
from src.ops.models.ops.sync_run_log import SyncRunLog
from src.utils import truncate_text


class OpsSyncRunLogStore(SyncRunLogStore):
    """ops 侧 run-log adapter：落到 ops.sync_run_log。"""

    MAX_LOG_MESSAGE_LENGTH = 16_000

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_log(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> SyncRunLog:
        log = SyncRunLog(
            execution_id=execution_id,
            job_name=job_name,
            run_type=run_type,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        # 保持历史语义：start_log 先提交，确保 run 失败也能留痕。
        self.session.commit()
        self.session.refresh(log)
        return log

    def finish_log(
        self,
        *,
        log: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        if not isinstance(log, SyncRunLog):
            raise TypeError("OpsSyncRunLogStore.finish_log expects SyncRunLog handle")
        log.status = status
        log.ended_at = datetime.now(timezone.utc)
        log.rows_fetched = rows_fetched
        log.rows_written = rows_written
        log.message = truncate_text(message, self.MAX_LOG_MESSAGE_LENGTH)


class OpsSyncJobStateStore(SyncJobStateStore):
    """ops 侧 job-state adapter：落到 ops.sync_job_state。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_last_success_date(self, *, job_name: str) -> date | None:
        state = self.session.get(SyncJobState, job_name)
        return state.last_success_date if state is not None else None

    def mark_success(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None:
        state = self.session.get(SyncJobState, job_name)
        if state is None:
            state = SyncJobState(
                job_name=job_name,
                target_table=target_table,
                full_sync_done=False,
            )
            self.session.add(state)
        state.target_table = target_table
        state.last_success_date = last_success_date
        state.last_success_at = datetime.now(timezone.utc)
        state.last_cursor = last_cursor

    def reconcile_success_date(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date,
    ) -> None:
        state = self.session.get(SyncJobState, job_name)
        if state is None:
            state = SyncJobState(
                job_name=job_name,
                target_table=target_table,
                full_sync_done=False,
                last_success_at=datetime.now(timezone.utc),
                last_success_date=last_success_date,
            )
            self.session.add(state)
            return
        state.target_table = target_table
        state.last_success_date = last_success_date

    def mark_full_sync_done(self, *, job_name: str, target_table: str) -> None:
        state = self.session.get(SyncJobState, job_name)
        if state is None:
            state = SyncJobState(
                job_name=job_name,
                target_table=target_table,
                full_sync_done=True,
                last_success_at=datetime.now(timezone.utc),
            )
            self.session.add(state)
            return
        state.target_table = target_table
        state.last_success_date = None
        state.last_cursor = None
        state.last_success_at = datetime.now(timezone.utc)
        state.full_sync_done = True
