from __future__ import annotations

from datetime import date

from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunRecorder


class NullSyncRunRecorder(SyncRunRecorder):
    def start_run(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> object:
        _ = (job_name, run_type, execution_id)
        return object()

    def finish_run(
        self,
        *,
        handle: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        _ = (handle, status, rows_fetched, rows_written, message)
        return None


class NullSyncJobStateStore(SyncJobStateStore):
    def get_last_success_date(self, *, job_name: str) -> date | None:
        _ = job_name
        return None

    def mark_success(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None:
        _ = (job_name, target_table, last_success_date, last_cursor)
        return None

    def reconcile_success_date(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date,
    ) -> None:
        _ = (job_name, target_table, last_success_date)
        return None

    def mark_full_sync_done(self, *, job_name: str, target_table: str) -> None:
        _ = (job_name, target_table)
        return None

    def record_execution_outcome(
        self,
        *,
        job_name: str,
        target_table: str,
        run_type: str,
        run_profile: str | None = None,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
        rows_committed: int | None = None,
    ) -> None:
        _ = (job_name, target_table, run_type, run_profile, last_success_date, last_cursor, rows_committed)
        return None
