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
            fetched, written, result_date, message = self.execute(run_type=run_type, execution_id=execution_id, **kwargs)
            self.dao.sync_run_log.finish_log(log, "SUCCESS", fetched, written, message)
            if result_date:
                self.dao.sync_job_state.mark_success(self.job_name, self.target_table, result_date)
            if run_type == "FULL":
                self.dao.sync_job_state.mark_full_sync_done(self.job_name, self.target_table)
            self.session.commit()
            return SyncResult(
                job_name=self.job_name,
                run_type=run_type,
                rows_fetched=fetched,
                rows_written=written,
                trade_date=result_date,
                message=message,
            )
        except Exception as exc:
            self.session.rollback()
            self.dao.sync_run_log.finish_log(log, "FAILED", 0, 0, str(exc))
            self.session.commit()
            raise

    def ensure_not_canceled(self, execution_id: int | None) -> None:
        if execution_id is None:
            return
        execution = self.session.get(JobExecution, execution_id)
        if execution is not None and execution.cancel_requested_at is not None:
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")

    @abstractmethod
    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        raise NotImplementedError
