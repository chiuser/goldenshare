from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from src.dao.factory import DAOFactory
from src.models.ops.job_execution import JobExecution
from src.operations.runtime.errors import ExecutionCanceledError
from src.schemas import SyncResult


class BaseSyncService(ABC):
    job_name: str
    target_table: str

    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.logger = logging.getLogger(self.__class__.__name__)

    def run_full(self, **kwargs: Any) -> SyncResult:
        return self._run("FULL", **kwargs)

    def run_incremental(self, trade_date: date | None = None, **kwargs: Any) -> SyncResult:
        return self._run("INCREMENTAL", trade_date=trade_date, **kwargs)

    def _run(self, run_type: str, **kwargs: Any) -> SyncResult:
        execution_id = kwargs.pop("execution_id", None)
        log = self.dao.sync_run_log.start_log(self.job_name, run_type, execution_id=execution_id)
        try:
            self.ensure_not_canceled(execution_id)
            fetched, written, result_date, message = self.execute(run_type=run_type, execution_id=execution_id, **kwargs)
            self.dao.sync_run_log.finish_log(log, "SUCCESS", fetched, written, message)
            if result_date:
                self.dao.sync_job_state.mark_success(self.job_name, self.target_table, result_date)
            if run_type == "FULL":
                self.dao.sync_job_state.mark_full_sync_done(self.job_name, self.target_table)
            self.session.commit()
            self._refresh_dataset_snapshot()
            return SyncResult(
                job_name=self.job_name,
                run_type=run_type,
                rows_fetched=fetched,
                rows_written=written,
                trade_date=result_date,
                message=message,
            )
        except ExecutionCanceledError as exc:
            self.session.rollback()
            self.dao.sync_run_log.finish_log(log, "CANCELED", 0, 0, str(exc))
            self.session.commit()
            self._refresh_dataset_snapshot()
            raise
        except Exception as exc:
            self.session.rollback()
            self.dao.sync_run_log.finish_log(log, "FAILED", 0, 0, str(exc))
            self.session.commit()
            self._refresh_dataset_snapshot()
            raise

    def _refresh_dataset_snapshot(self) -> None:
        resource_keys = self._snapshot_resource_keys()
        if not resource_keys:
            return
        try:
            # Keep snapshot in sync even when sync jobs are executed directly via CLI.
            from src.operations.services.dataset_status_snapshot_service import DatasetStatusSnapshotService

            DatasetStatusSnapshotService().refresh_resources(self.session, resource_keys)
        except Exception as exc:  # pragma: no cover - snapshot refresh should never break sync jobs
            self.logger.warning("skip dataset snapshot refresh for %s: %s", self.job_name, exc)

    def _snapshot_resource_keys(self) -> list[str]:
        candidates: list[str] = []
        if self.job_name.startswith("sync_"):
            candidates.append(self.job_name.removeprefix("sync_"))
        if "." in self.target_table:
            candidates.append(self.target_table.split(".", 1)[1])
        seen: set[str] = set()
        deduped: list[str] = []
        for key in candidates:
            if key and key not in seen:
                seen.add(key)
                deduped.append(key)
        return deduped

    def ensure_not_canceled(self, execution_id: int | None) -> None:
        if execution_id is None:
            return
        execution = self.session.get(JobExecution, execution_id)
        if execution is not None and execution.cancel_requested_at is not None:
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")

    @abstractmethod
    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        raise NotImplementedError
