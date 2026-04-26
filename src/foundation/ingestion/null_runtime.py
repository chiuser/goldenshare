from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.kernel.contracts.sync_state_store import SyncExecutionResultStore, SyncRunRecorder


class NullExecutionContext(SyncExecutionContext):
    def is_cancel_requested(self, *, execution_id: int) -> bool:
        return False

    def update_progress(
        self,
        *,
        execution_id: int,
        current: int,
        total: int,
        message: str,
        rows_fetched: int | None = None,
        rows_saved: int | None = None,
        rows_rejected: int | None = None,
        current_object: dict[str, Any] | None = None,
    ) -> None:
        return None


class NullRunRecorder(SyncRunRecorder):
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


class NullExecutionResultStore(SyncExecutionResultStore):
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
