from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_errors import ExecutionCanceledError
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput, ValidatedDatasetActionRequest
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.null_runtime import NullExecutionContext, NullExecutionResultStore, NullRunRecorder
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.kernel.contracts.sync_state_store import SyncExecutionResultStore, SyncRunRecorder


@dataclass(slots=True)
class DatasetMaintainResult:
    dataset_key: str
    run_type: str
    rows_fetched: int = 0
    rows_written: int = 0
    trade_date: date | None = None
    message: str | None = None


class DatasetMaintainService:
    _REQUEST_ENVELOPE_KEYS = frozenset(
        {
            "request_id",
            "execution_id",
            "run_profile",
            "trigger_source",
            "source_key",
            "trade_date",
            "start_date",
            "end_date",
            "correlation_id",
            "rerun_id",
            "_plan",
            "_action_request",
        }
    )

    def __init__(
        self,
        session,
        *,
        dataset_key: str,
        execution_context: SyncExecutionContext | None = None,
        run_recorder: SyncRunRecorder | None = None,
        execution_result_store: SyncExecutionResultStore | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.definition = get_dataset_definition(dataset_key)
        self.dataset_key = dataset_key
        self.execution_context = execution_context or NullExecutionContext()
        self.run_recorder = run_recorder or NullRunRecorder()
        self.execution_result_store = execution_result_store or NullExecutionResultStore()
        self.executor = IngestionExecutor(session)
        self.resolver = DatasetActionResolver(session)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cli_progress_reporter = None

    def set_execution_context(self, execution_context: SyncExecutionContext | None) -> None:
        self.execution_context = execution_context or NullExecutionContext()

    def set_state_stores(
        self,
        *,
        run_recorder: SyncRunRecorder | None = None,
        execution_result_store: SyncExecutionResultStore | None = None,
    ) -> None:
        self.run_recorder = run_recorder or NullRunRecorder()
        self.execution_result_store = execution_result_store or NullExecutionResultStore()

    def set_cli_progress_reporter(self, progress_reporter) -> None:  # type: ignore[no-untyped-def]
        self._cli_progress_reporter = progress_reporter

    def run_full(self, **kwargs: Any) -> DatasetMaintainResult:
        return self._run("FULL", **kwargs)

    def run_incremental(self, trade_date: date | None = None, **kwargs: Any) -> DatasetMaintainResult:
        return self._run("INCREMENTAL", trade_date=trade_date, **kwargs)

    def _run(self, run_type: str, **kwargs: Any) -> DatasetMaintainResult:
        execution_id = kwargs.pop("execution_id", None)
        request = kwargs.pop("_action_request", None) or self._build_action_request(
            run_type=run_type,
            execution_id=execution_id,
            trade_date=kwargs.get("trade_date"),
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            month=kwargs.get("month"),
            start_month=kwargs.get("start_month"),
            end_month=kwargs.get("end_month"),
            filters=self._build_request_params(kwargs),
            trigger_source=str(kwargs.get("trigger_source") or "manual"),
        )
        plan = kwargs.pop("_plan", None) or self.resolver.build_plan(request)
        validated = self._validated_request_from_plan(request=request, plan=plan)
        run_handle = self._start_run_handle(run_type=run_type, execution_id=execution_id)
        self.ensure_not_canceled(execution_id)
        try:
            summary = self.executor.run(
                request=validated,
                definition=self.definition,
                units=plan.units,
                cancel_checker=self._is_cancel_requested,
                progress_reporter=self._progress_reporter,
            )
            committed_rows = summary.rows_committed
            if self.definition.transaction.commit_policy != "unit":
                self.session.commit()
                committed_rows = summary.rows_written
            self._finish_success(
                run_handle=run_handle,
                run_type=run_type,
                rows_fetched=summary.rows_fetched,
                rows_written=committed_rows,
                result_date=summary.result_date,
                message=summary.message,
            )
            return DatasetMaintainResult(
                dataset_key=self.dataset_key,
                run_type=run_type,
                rows_fetched=summary.rows_fetched,
                rows_written=committed_rows,
                trade_date=summary.result_date,
                message=summary.message,
            )
        except ExecutionCanceledError as exc:
            if self.definition.transaction.commit_policy != "unit":
                self.session.rollback()
            self._finish_failure(run_handle=run_handle, status="CANCELED", message=str(exc))
            raise
        except Exception as exc:
            if self.definition.transaction.commit_policy != "unit":
                self.session.rollback()
            self._finish_failure(run_handle=run_handle, status="FAILED", message=str(exc))
            raise

    def ensure_not_canceled(self, execution_id: int | None) -> None:
        if execution_id is None:
            return
        if self.execution_context.is_cancel_requested(execution_id=execution_id):
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")

    def _build_action_request(
        self,
        *,
        run_type: str,
        execution_id: int | None,
        trade_date: date | None,
        start_date: date | None,
        end_date: date | None,
        month: str | None,
        start_month: str | None,
        end_month: str | None,
        filters: dict[str, Any],
        trigger_source: str,
    ) -> DatasetActionRequest:
        if run_type == "INCREMENTAL":
            mode = "point"
        elif trade_date is not None or month is not None:
            mode = "point"
        elif start_date is not None or end_date is not None or start_month is not None or end_month is not None:
            mode = "range"
        else:
            mode = "none"
        return DatasetActionRequest(
            dataset_key=self.dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(
                mode=mode,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                month=str(month).strip() if month not in (None, "") else None,
                start_month=str(start_month).strip() if start_month not in (None, "") else None,
                end_month=str(end_month).strip() if end_month not in (None, "") else None,
            ),
            filters=filters,
            trigger_source=trigger_source,
            execution_id=execution_id,
        )

    @classmethod
    def _build_request_params(cls, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in kwargs.items() if key not in cls._REQUEST_ENVELOPE_KEYS and not key.startswith("_")}

    @staticmethod
    def _validated_request_from_plan(*, request: DatasetActionRequest, plan) -> ValidatedDatasetActionRequest:  # type: ignore[no-untyped-def]
        return ValidatedDatasetActionRequest(
            request_id=uuid4().hex,
            dataset_key=plan.dataset_key,
            action=request.action,
            run_profile=plan.run_profile,
            trigger_source=request.trigger_source,
            params=dict(request.filters or {}),
            source_key=str((request.filters or {}).get("source_key") or "").strip() or None,
            trade_date=request.time_input.trade_date,
            start_date=request.time_input.start_date,
            end_date=request.time_input.end_date,
            execution_id=request.execution_id,
        )

    def _start_run_handle(self, *, run_type: str, execution_id: int | None) -> object:
        try:
            return self.run_recorder.start_run(job_name=self.dataset_key, run_type=run_type, execution_id=execution_id)
        except Exception:
            self.logger.warning("Failed to start run recorder.", exc_info=True)
            return object()

    def _finish_success(
        self,
        *,
        run_handle: object,
        run_type: str,
        rows_fetched: int,
        rows_written: int,
        result_date: date | None,
        message: str | None,
    ) -> None:
        try:
            self.run_recorder.finish_run(
                handle=run_handle,
                status="SUCCESS",
                rows_fetched=rows_fetched,
                rows_written=rows_written,
                message=message,
            )
        except Exception:
            self.logger.warning("Failed to finish run recorder.", exc_info=True)
        try:
            self.execution_result_store.record_execution_outcome(
                job_name=self.dataset_key,
                target_table=self.definition.storage.target_table,
                run_type=run_type,
                run_profile=None,
                last_success_date=result_date,
                rows_committed=rows_written,
            )
        except Exception:
            self.logger.warning("Failed to persist execution outcome.", exc_info=True)

    def _finish_failure(self, *, run_handle: object, status: str, message: str) -> None:
        try:
            self.run_recorder.finish_run(
                handle=run_handle,
                status=status,
                rows_fetched=0,
                rows_written=0,
                message=message,
            )
        except Exception:
            self.logger.warning("Failed to finish failed run recorder.", exc_info=True)

    def _is_cancel_requested(self, execution_id: int) -> bool:
        return self.execution_context.is_cancel_requested(execution_id=execution_id)

    def _progress_reporter(self, progress_snapshot, message: str) -> None:  # type: ignore[no-untyped-def]
        rows_saved = progress_snapshot.rows_committed or progress_snapshot.rows_written
        try:
            if progress_snapshot.execution_id is not None:
                self.execution_context.update_progress(
                    execution_id=progress_snapshot.execution_id,
                    current=progress_snapshot.unit_done + progress_snapshot.unit_failed,
                    total=progress_snapshot.unit_total,
                    message=message,
                    rows_fetched=progress_snapshot.rows_fetched,
                    rows_saved=rows_saved,
                    rows_rejected=progress_snapshot.rows_rejected,
                    current_object=progress_snapshot.current_object,
                )
        except Exception:
            self.logger.warning("Failed to persist execution progress update.", exc_info=True)
        if callable(self._cli_progress_reporter):
            try:
                self._cli_progress_reporter(progress_snapshot, message)
            except Exception:
                pass
