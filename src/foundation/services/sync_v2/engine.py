from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.foundation.services.sync.errors import ExecutionCanceledError
from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    EngineRunSummary,
    RunRequest,
)
from src.foundation.services.sync_v2.error_mapper import SyncV2ErrorMapper
from src.foundation.services.sync_v2.errors import StructuredError, SyncV2Error
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.observer import SyncV2Observer
from src.foundation.services.sync_v2.planner import SyncV2Planner
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.sync_v2.worker_client import SyncV2WorkerClient
from src.foundation.services.sync_v2.writer import SyncV2Writer


class SyncV2Engine:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.validator = ContractValidator()
        self.planner = SyncV2Planner(session)
        self.worker = SyncV2WorkerClient()
        self.normalizer = SyncV2Normalizer()
        self.writer = SyncV2Writer(session)
        self.error_mapper = SyncV2ErrorMapper()

    def run(
        self,
        *,
        request: RunRequest,
        contract: DatasetSyncContract,
        strict_contract: bool,
        cancel_checker=None,  # type: ignore[no-untyped-def]
        progress_reporter=None,  # type: ignore[no-untyped-def]
    ) -> EngineRunSummary:
        validated = self.validator.validate(request=request, contract=contract, strict=strict_contract)
        units = self.planner.plan(validated, contract)
        observer = SyncV2Observer(progress_reporter=progress_reporter)

        rows_fetched = 0
        rows_written = 0
        unit_done = 0
        unit_failed = 0
        error_counts: dict[str, int] = {}

        total_units = len(units)
        for index, unit in enumerate(units, start=1):
            self._ensure_not_canceled(cancel_checker=cancel_checker, execution_id=validated.execution_id)
            try:
                fetched = self.worker.fetch(contract=contract, unit=unit)
                normalized = self.normalizer.normalize(contract=contract, fetch_result=fetched)
                self.normalizer.raise_if_all_rejected(normalized)
                written = self.writer.write(contract=contract, batch=normalized)
                rows_fetched += len(fetched.rows_raw)
                rows_written += written.rows_written
                unit_done += 1
            except SyncV2Error as exc:
                unit_failed += 1
                error_code = exc.structured_error.error_code
                error_counts[error_code] = error_counts.get(error_code, 0) + 1
                raise
            except Exception as exc:
                unit_failed += 1
                structured = self.error_mapper.map_exception(exc=exc, phase="engine", unit_id=unit.unit_id)
                error_counts[structured.error_code] = error_counts.get(structured.error_code, 0) + 1
                raise SyncV2Error(structured) from exc
            finally:
                observer.report_progress(
                    execution_id=validated.execution_id,
                    dataset_key=validated.dataset_key,
                    unit_total=total_units,
                    unit_done=unit_done,
                    unit_failed=unit_failed,
                    rows_fetched=rows_fetched,
                    rows_written=rows_written,
                    message=(
                        f"{contract.observe_spec.progress_label}: "
                        f"{index}/{total_units} fetched={rows_fetched} written={rows_written}"
                    ),
                )

        return EngineRunSummary(
            dataset_key=validated.dataset_key,
            run_profile=validated.run_profile,
            unit_total=total_units,
            unit_done=unit_done,
            unit_failed=unit_failed,
            rows_fetched=rows_fetched,
            rows_written=rows_written,
            result_date=self._resolve_result_date(validated),
            message=f"units={total_units} done={unit_done} failed={unit_failed}",
            error_counts=error_counts,
        )

    @staticmethod
    def _resolve_result_date(validated) -> date | None:  # type: ignore[no-untyped-def]
        if validated.run_profile == "point_incremental":
            return validated.trade_date
        if validated.run_profile == "range_rebuild":
            return validated.end_date
        return None

    @staticmethod
    def _ensure_not_canceled(*, cancel_checker, execution_id: int | None) -> None:  # type: ignore[no-untyped-def]
        if execution_id is None or cancel_checker is None:
            return
        if cancel_checker(execution_id):
            raise ExecutionCanceledError("任务已收到停止请求，正在结束处理。")
