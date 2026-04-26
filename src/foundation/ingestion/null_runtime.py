from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.kernel.contracts.ingestion_execution_context import IngestionExecutionContext
from src.foundation.kernel.contracts.ingestion_state_store import IngestionExecutionResultStore, IngestionRunRecorder


class NullExecutionContext(IngestionExecutionContext):
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


class NullRunRecorder(IngestionRunRecorder):
    def start_run(self, *, dataset_key: str, run_mode: str, execution_id: int | None = None) -> object:
        _ = (dataset_key, run_mode, execution_id)
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


class NullExecutionResultStore(IngestionExecutionResultStore):
    def record_execution_outcome(
        self,
        *,
        dataset_key: str,
        target_table: str,
        run_mode: str,
        run_profile: str | None = None,
        last_success_date: date | None = None,
        rows_committed: int | None = None,
    ) -> None:
        _ = (dataset_key, target_table, run_mode, run_profile, last_success_date, rows_committed)
        return None
