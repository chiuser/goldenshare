from __future__ import annotations

from datetime import date
from typing import Protocol

from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunLogStore


class _SyncRunLogDAOProtocol(Protocol):
    def start_log(self, job_name: str, run_type: str, execution_id: int | None = None) -> object: ...

    def finish_log(self, log: object, status: str, rows_fetched: int, rows_written: int, message: str | None = None) -> None: ...


class _SyncJobStateDAOProtocol(Protocol):
    def get_last_success_date(self, job_name: str) -> date | None: ...

    def mark_success(
        self,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None: ...

    def reconcile_success_date(self, job_name: str, target_table: str, last_success_date: date) -> None: ...

    def mark_full_sync_done(self, job_name: str, target_table: str) -> None: ...


class NullSyncRunLogStore(SyncRunLogStore):
    def start_log(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> object:
        _ = (job_name, run_type, execution_id)
        return object()

    def finish_log(
        self,
        *,
        log: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        _ = (log, status, rows_fetched, rows_written, message)
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


class DaoSyncRunLogStore(SyncRunLogStore):
    """兼容适配：把 foundation DAO 适配到 run-log contract。"""

    def __init__(self, dao: _SyncRunLogDAOProtocol) -> None:
        self.dao = dao

    def start_log(self, *, job_name: str, run_type: str, execution_id: int | None = None) -> object:
        return self.dao.start_log(job_name, run_type, execution_id=execution_id)

    def finish_log(
        self,
        *,
        log: object,
        status: str,
        rows_fetched: int,
        rows_written: int,
        message: str | None = None,
    ) -> None:
        self.dao.finish_log(log, status, rows_fetched, rows_written, message)


class DaoSyncJobStateStore(SyncJobStateStore):
    """兼容适配：把 foundation DAO 适配到 job-state contract。"""

    def __init__(self, dao: _SyncJobStateDAOProtocol) -> None:
        self.dao = dao

    def get_last_success_date(self, *, job_name: str) -> date | None:
        return self.dao.get_last_success_date(job_name)

    def mark_success(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date | None = None,
        last_cursor: str | None = None,
    ) -> None:
        self.dao.mark_success(
            job_name,
            target_table,
            last_success_date=last_success_date,
            last_cursor=last_cursor,
        )

    def reconcile_success_date(
        self,
        *,
        job_name: str,
        target_table: str,
        last_success_date: date,
    ) -> None:
        self.dao.reconcile_success_date(job_name, target_table, last_success_date)

    def mark_full_sync_done(self, *, job_name: str, target_table: str) -> None:
        self.dao.mark_full_sync_done(job_name, target_table)

