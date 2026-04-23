from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from src.foundation.services.sync_v2.base_sync_service import BaseSyncService
from src.foundation.services.sync_v2.contracts import DatasetSyncContract, RunRequest
from src.foundation.services.sync_v2.engine import SyncV2Engine
from src.foundation.services.sync_v2.errors import SyncV2Error


class SyncV2Service(BaseSyncService):
    def __init__(self, session: Session, *, contract: DatasetSyncContract, strict_contract: bool) -> None:
        self.contract = contract
        self.strict_contract = strict_contract
        self.engine = SyncV2Engine(session)
        self._cli_progress_reporter = None
        self.job_name = contract.job_name
        self.target_table = contract.write_spec.target_table
        super().__init__(session)

    def set_cli_progress_reporter(self, progress_reporter) -> None:  # type: ignore[no-untyped-def]
        self._cli_progress_reporter = progress_reporter

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        execution_id = kwargs.get("execution_id")
        request = RunRequest(
            request_id=str(kwargs.get("request_id") or uuid4().hex),
            execution_id=execution_id,
            dataset_key=self.contract.dataset_key,
            run_profile=self._resolve_run_profile(run_type=run_type, kwargs=kwargs),
            trigger_source=str(kwargs.get("trigger_source") or "manual"),
            source_key=self._to_optional_text(kwargs.get("source_key")),
            trade_date=kwargs.get("trade_date"),
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            correlation_id=self._to_optional_text(kwargs.get("correlation_id")),
            rerun_id=self._to_optional_text(kwargs.get("rerun_id")),
            params={key: value for key, value in kwargs.items() if key != "execution_id"},
        )

        def progress_reporter(progress_snapshot, message: str) -> None:  # type: ignore[no-untyped-def]
            self._update_execution_progress(
                execution_id=progress_snapshot.execution_id,
                current=progress_snapshot.unit_done + progress_snapshot.unit_failed,
                total=progress_snapshot.unit_total,
                message=message,
            )
            if callable(self._cli_progress_reporter):
                try:
                    self._cli_progress_reporter(progress_snapshot, message)
                except Exception:
                    pass

        def cancel_checker(current_execution_id: int) -> bool:
            return self.execution_context.is_cancel_requested(execution_id=current_execution_id)

        try:
            summary = self.engine.run(
                request=request,
                contract=self.contract,
                strict_contract=self.strict_contract,
                cancel_checker=cancel_checker,
                progress_reporter=progress_reporter,
            )
        except SyncV2Error as exc:
            code = exc.structured_error.error_code
            raise RuntimeError(f"[{code}] {exc.structured_error.message}") from exc
        return summary.rows_fetched, summary.rows_written, summary.result_date, summary.message

    @staticmethod
    def _resolve_run_profile(*, run_type: str, kwargs: dict[str, Any]) -> str:
        explicit = str(kwargs.get("run_profile") or "").strip()
        if explicit in {"point_incremental", "range_rebuild", "snapshot_refresh"}:
            return explicit
        if run_type == "INCREMENTAL":
            return "point_incremental"
        if kwargs.get("trade_date") not in (None, ""):
            return "point_incremental"
        if kwargs.get("start_date") not in (None, "") or kwargs.get("end_date") not in (None, ""):
            return "range_rebuild"
        return "snapshot_refresh"

    @staticmethod
    def _to_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
