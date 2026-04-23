from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.kernel.contracts.index_series_active_store import IndexSeriesActiveStore
from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunLogStore
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.schemas import SyncResult
from src.foundation.services.sync_v2.execution_errors import ExecutionCanceledError
from src.foundation.services.sync_v2.sync_execution_context import NullSyncExecutionContext
from src.foundation.services.sync_v2.sync_state_store import (
    DaoSyncJobStateStore,
    DaoSyncRunLogStore,
    NullSyncJobStateStore,
    NullSyncRunLogStore,
)


class BaseSyncService(ABC):
    job_name: str
    target_table: str

    def __init__(
        self,
        session: Session,
        execution_context: SyncExecutionContext | None = None,
        run_log_store: SyncRunLogStore | None = None,
        job_state_store: SyncJobStateStore | None = None,
        index_series_active_store: IndexSeriesActiveStore | None = None,
    ) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.execution_context = execution_context or NullSyncExecutionContext()
        self.run_log_store = run_log_store or DaoSyncRunLogStore(self.dao.sync_run_log)
        self.job_state_store = job_state_store or DaoSyncJobStateStore(self.dao.sync_job_state)
        self.index_series_active_store = index_series_active_store or self.dao.index_series_active
        self.logger = logging.getLogger(self.__class__.__name__)
        self._assert_no_legacy_raw_schema_route()

    def set_execution_context(self, execution_context: SyncExecutionContext | None) -> None:
        self.execution_context = execution_context or NullSyncExecutionContext()

    def set_state_stores(
        self,
        *,
        run_log_store: SyncRunLogStore | None = None,
        job_state_store: SyncJobStateStore | None = None,
    ) -> None:
        self.run_log_store = run_log_store or NullSyncRunLogStore()
        self.job_state_store = job_state_store or NullSyncJobStateStore()

    def set_index_series_active_store(self, index_series_active_store: IndexSeriesActiveStore | None) -> None:
        self.index_series_active_store = index_series_active_store or self.dao.index_series_active

    def run_full(self, **kwargs: Any) -> SyncResult:
        return self._run("FULL", **kwargs)

    def run_incremental(self, trade_date: date | None = None, **kwargs: Any) -> SyncResult:
        return self._run("INCREMENTAL", trade_date=trade_date, **kwargs)

    def _run(self, run_type: str, **kwargs: Any) -> SyncResult:
        execution_id = kwargs.pop("execution_id", None)
        log = self.run_log_store.start_log(job_name=self.job_name, run_type=run_type, execution_id=execution_id)
        try:
            self.ensure_not_canceled(execution_id)
            fetched, written, result_date, message = self.execute(run_type=run_type, execution_id=execution_id, **kwargs)
            self.run_log_store.finish_log(
                log=log,
                status="SUCCESS",
                rows_fetched=fetched,
                rows_written=written,
                message=message,
            )
            if result_date:
                self.job_state_store.mark_success(
                    job_name=self.job_name,
                    target_table=self.target_table,
                    last_success_date=result_date,
                )
            if run_type == "FULL":
                self.job_state_store.mark_full_sync_done(job_name=self.job_name, target_table=self.target_table)
            self.session.commit()
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
            self.run_log_store.finish_log(
                log=log,
                status="CANCELED",
                rows_fetched=0,
                rows_written=0,
                message=str(exc),
            )
            self.session.commit()
            raise
        except Exception as exc:
            self.session.rollback()
            self.run_log_store.finish_log(
                log=log,
                status="FAILED",
                rows_fetched=0,
                rows_written=0,
                message=str(exc),
            )
            self.session.commit()
            raise

    def ensure_not_canceled(self, execution_id: int | None) -> None:
        if execution_id is None:
            return
        if self.execution_context.is_cancel_requested(execution_id=execution_id):
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")

    def _update_execution_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        if execution_id is None:
            return
        try:
            self.execution_context.update_progress(
                execution_id=execution_id,
                current=current,
                total=total,
                message=message,
            )
        except Exception:
            self.logger.warning("Failed to persist sync progress update.", exc_info=True)

    def _assert_no_legacy_raw_schema_route(self) -> None:
        """
        发布闸门：除 BIYING 专属 raw 路由外，任何 raw DAO 若仍指向 legacy `raw` schema，
        直接阻断任务执行，避免切换后再次写回旧表。
        """
        offenders: list[str] = []
        for attr_name in dir(self.dao):
            if not attr_name.startswith("raw_"):
                continue
            if attr_name.startswith("raw_biying_"):
                continue
            dao_obj = getattr(self.dao, attr_name, None)
            model = getattr(dao_obj, "model", None)
            table = getattr(model, "__table__", None)
            schema = getattr(table, "schema", None)
            if schema == "raw":
                offenders.append(attr_name)
        if offenders:
            joined = ", ".join(sorted(offenders))
            raise RuntimeError(
                "Detected legacy raw schema route(s): "
                f"{joined}. Please migrate these routes to raw_tushare before running sync jobs."
            )

    @abstractmethod
    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        raise NotImplementedError
