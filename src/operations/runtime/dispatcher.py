from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.models.ops.job_execution import JobExecution
from src.models.ops.job_execution_event import JobExecutionEvent
from src.models.ops.job_execution_step import JobExecutionStep
from src.operations.runtime.errors import ExecutionCanceledError
from src.operations.specs import get_job_spec, get_workflow_spec
from src.services.history_backfill_service import HistoryBackfillService
from src.services.sync.registry import build_sync_service
from src.web.exceptions import WebAppError


@dataclass(slots=True)
class DispatchOutcome:
    status: str
    rows_fetched: int = 0
    rows_written: int = 0
    summary_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class OperationsDispatcher:
    def dispatch(self, session: Session, execution: JobExecution) -> DispatchOutcome:
        if execution.spec_type == "job":
            job_spec = get_job_spec(execution.spec_key)
            if job_spec is None:
                raise WebAppError(status_code=404, code="not_found", message="Job spec does not exist")
            return self._dispatch_job(session, execution, job_spec)

        if execution.spec_type == "workflow":
            workflow_spec = get_workflow_spec(execution.spec_key)
            if workflow_spec is None:
                raise WebAppError(status_code=404, code="not_found", message="Workflow spec does not exist")
            return self._dispatch_workflow(session, execution, workflow_spec)

        raise WebAppError(status_code=422, code="validation_error", message="Unsupported execution spec_type")

    def _dispatch_job(self, session: Session, execution: JobExecution, job_spec) -> DispatchOutcome:  # type: ignore[no-untyped-def]
        step = self._create_step(session, execution_id=execution.id, step_key=job_spec.key, display_name=job_spec.display_name, sequence_no=1)
        self._event(session, execution.id, "step_started", step_id=step.id, message=job_spec.display_name)
        session.commit()
        try:
            rows_fetched, rows_written, summary_message = self._run_job(session, execution, job_spec, step.id)
            step.status = "success"
            step.ended_at = datetime.now(timezone.utc)
            step.rows_fetched = rows_fetched
            step.rows_written = rows_written
            step.message = summary_message
            self._event(session, execution.id, "step_succeeded", step_id=step.id, message=summary_message)
            session.commit()
            return DispatchOutcome(
                status="success",
                rows_fetched=rows_fetched,
                rows_written=rows_written,
                summary_message=summary_message,
            )
        except ExecutionCanceledError as exc:
            session.rollback()
            step = session.get(JobExecutionStep, step.id)
            if step is not None:
                step.status = "canceled"
                step.ended_at = datetime.now(timezone.utc)
                step.message = str(exc)
            self._event(session, execution.id, "step_canceled", step_id=step.id if step else None, message=str(exc), level="WARNING")
            session.commit()
            return DispatchOutcome(
                status="canceled",
                summary_message=str(exc),
            )
        except Exception as exc:
            session.rollback()
            step = session.get(JobExecutionStep, step.id)
            if step is not None:
                step.status = "failed"
                step.ended_at = datetime.now(timezone.utc)
                step.message = str(exc)
            self._event(session, execution.id, "step_failed", step_id=step.id if step else None, message=str(exc), level="ERROR")
            session.commit()
            return DispatchOutcome(
                status="failed",
                error_code="execution_failed",
                error_message=str(exc),
                summary_message=str(exc),
            )

    def _dispatch_workflow(self, session: Session, execution: JobExecution, workflow_spec) -> DispatchOutcome:  # type: ignore[no-untyped-def]
        total_fetched = 0
        total_written = 0
        completed = 0
        last_message: str | None = None
        for sequence_no, workflow_step in enumerate(workflow_spec.steps, start=1):
            job_spec = get_job_spec(workflow_step.job_key)
            if job_spec is None:
                message = f"Workflow step job spec does not exist: {workflow_step.job_key}"
                self._event(session, execution.id, "failed", message=message, level="ERROR")
                session.commit()
                return DispatchOutcome(status="failed", error_code="workflow_invalid", error_message=message, summary_message=message)

            params = dict(execution.params_json or {})
            params.update(workflow_step.default_params)
            step_execution = JobExecution(
                id=execution.id,
                spec_type="job",
                spec_key=job_spec.key,
                trigger_source=execution.trigger_source,
                status=execution.status,
                requested_at=execution.requested_at,
                params_json=params,
            )
            step = self._create_step(
                session,
                execution_id=execution.id,
                step_key=workflow_step.step_key,
                display_name=workflow_step.display_name,
                sequence_no=sequence_no,
            )
            self._event(session, execution.id, "step_started", step_id=step.id, message=workflow_step.display_name)
            session.commit()
            try:
                rows_fetched, rows_written, summary_message = self._run_job(session, step_execution, job_spec, step.id)
                step.status = "success"
                step.ended_at = datetime.now(timezone.utc)
                step.rows_fetched = rows_fetched
                step.rows_written = rows_written
                step.message = summary_message
                self._event(session, execution.id, "step_succeeded", step_id=step.id, message=summary_message)
                session.commit()
                total_fetched += rows_fetched
                total_written += rows_written
                completed += 1
                last_message = summary_message
            except ExecutionCanceledError as exc:
                session.rollback()
                step = session.get(JobExecutionStep, step.id)
                if step is not None:
                    step.status = "canceled"
                    step.ended_at = datetime.now(timezone.utc)
                    step.message = str(exc)
                self._event(session, execution.id, "step_canceled", step_id=step.id if step else None, message=str(exc), level="WARNING")
                session.commit()
                return DispatchOutcome(
                    status="canceled",
                    rows_fetched=total_fetched,
                    rows_written=total_written,
                    summary_message=str(exc),
                )
            except Exception as exc:
                session.rollback()
                step = session.get(JobExecutionStep, step.id)
                if step is not None:
                    step.status = "failed"
                    step.ended_at = datetime.now(timezone.utc)
                    step.message = str(exc)
                self._event(session, execution.id, "step_failed", step_id=step.id if step else None, message=str(exc), level="ERROR")
                session.commit()
                return DispatchOutcome(
                    status="partial_success" if completed else "failed",
                    rows_fetched=total_fetched,
                    rows_written=total_written,
                    summary_message=str(exc),
                    error_code="workflow_step_failed",
                    error_message=str(exc),
                )

        return DispatchOutcome(
            status="success",
            rows_fetched=total_fetched,
            rows_written=total_written,
            summary_message=last_message or workflow_spec.display_name,
        )

    def _run_job(self, session: Session, execution: JobExecution, job_spec, step_id: int) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        params = dict(execution.params_json or {})
        if job_spec.executor_kind == "sync_service":
            return self._run_sync_job(session, execution, job_spec, params)
        if job_spec.executor_kind == "history_backfill_service":
            return self._run_backfill_job(session, execution, job_spec, params, step_id)
        if job_spec.executor_kind == "maintenance":
            return self._run_maintenance_job(session, job_spec)
        raise ValueError(f"Unsupported executor kind: {job_spec.executor_kind}")

    def _run_sync_job(self, session: Session, execution: JobExecution, job_spec, params: dict[str, Any]) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        _, resource = job_spec.key.split(".", 1)
        service = build_sync_service(resource, session)
        if job_spec.category == "sync_daily":
            trade_date = params.get("trade_date")
            parsed_trade_date = self._parse_date(trade_date) if trade_date else None
            result = service.run_incremental(trade_date=parsed_trade_date, execution_id=execution.id)
        else:
            result = service.run_full(execution_id=execution.id, **self._normalize_dates(params))
        return result.rows_fetched, result.rows_written, result.message

    def _run_backfill_job(
        self,
        session: Session,
        execution: JobExecution,
        job_spec,
        params: dict[str, Any],
        step_id: int,
    ) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        service = HistoryBackfillService(session)
        normalized = self._normalize_dates(params)

        def on_progress(message: str) -> None:
            progress_payload = self._build_progress_payload(message)
            self._update_execution_progress(session, execution.id, progress_payload)
            self._event(
                session,
                execution.id,
                "step_progress",
                step_id=step_id,
                message=message,
                payload_json=progress_payload,
            )
            session.commit()

        resource = job_spec.key.split(".", 1)[1]
        if job_spec.category == "backfill_trade_cal":
            summary = service.backfill_trade_calendar(
                self._require_date(normalized, "start_date"),
                self._require_date(normalized, "end_date"),
                exchange=normalized.get("exchange"),
                execution_id=execution.id,
            )
        elif job_spec.category == "backfill_equity_series":
            summary = service.backfill_equity_series(
                resource=resource,
                start_date=self._require_date(normalized, "start_date"),
                end_date=self._require_date(normalized, "end_date"),
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        elif job_spec.category == "backfill_by_trade_date":
            summary = service.backfill_by_trade_dates(
                resource=resource,
                start_date=self._require_date(normalized, "start_date"),
                end_date=self._require_date(normalized, "end_date"),
                exchange=normalized.get("exchange"),
                ts_code=normalized.get("ts_code"),
                con_code=normalized.get("con_code"),
                idx_type=normalized.get("idx_type"),
                market=normalized.get("market"),
                hot_type=normalized.get("hot_type"),
                is_new=normalized.get("is_new"),
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        elif job_spec.category == "backfill_low_frequency":
            summary = service.backfill_low_frequency_by_security(
                resource=resource,
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        elif job_spec.category == "backfill_fund_series":
            summary = service.backfill_fund_series(
                resource=resource,
                start_date=self._require_date(normalized, "start_date"),
                end_date=self._require_date(normalized, "end_date"),
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        elif job_spec.category == "backfill_index_series":
            summary = service.backfill_index_series(
                resource=resource,
                start_date=self._require_date(normalized, "start_date"),
                end_date=self._require_date(normalized, "end_date"),
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        else:
            raise ValueError(f"Unsupported backfill category: {job_spec.category}")
        return summary.rows_fetched, summary.rows_written, f"units={summary.units_processed}"

    def _run_maintenance_job(self, session: Session, job_spec) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        if job_spec.key != "maintenance.rebuild_dm":
            raise ValueError(f"Unsupported maintenance job: {job_spec.key}")
        session.execute(text("REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"))
        session.commit()
        return 0, 0, "materialized view refreshed"

    @staticmethod
    def _create_step(
        session: Session,
        *,
        execution_id: int,
        step_key: str,
        display_name: str,
        sequence_no: int,
    ) -> JobExecutionStep:
        step = JobExecutionStep(
            execution_id=execution_id,
            step_key=step_key,
            display_name=display_name,
            sequence_no=sequence_no,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.add(step)
        session.flush()
        return step

    @staticmethod
    def _event(
        session: Session,
        execution_id: int,
        event_type: str,
        *,
        step_id: int | None = None,
        level: str = "INFO",
        message: str | None = None,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            JobExecutionEvent(
                execution_id=execution_id,
                step_id=step_id,
                event_type=event_type,
                level=level,
                message=message,
                payload_json=payload_json or {},
                occurred_at=datetime.now(timezone.utc),
            )
        )

    def _update_execution_progress(self, session: Session, execution_id: int, payload_json: dict[str, Any]) -> None:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            return
        execution.progress_message = str(payload_json.get("progress_message") or execution.progress_message or "")
        execution.last_progress_at = datetime.now(timezone.utc)

        current = self._optional_int(payload_json.get("progress_current"))
        total = self._optional_int(payload_json.get("progress_total"))
        percent = self._optional_int(payload_json.get("progress_percent"))

        if current is not None:
            execution.progress_current = current
        if total is not None:
            execution.progress_total = total
        if percent is not None:
            execution.progress_percent = max(0, min(100, percent))

    @staticmethod
    def _build_progress_payload(message: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"progress_message": message}
        import re

        match = re.search(r"(\d+)\s*/\s*(\d+)", message)
        if not match:
            return payload

        current = int(match.group(1))
        total = int(match.group(2))
        payload["progress_current"] = current
        payload["progress_total"] = total
        payload["progress_percent"] = 0 if total <= 0 else round(current / total * 100)
        return payload

    @staticmethod
    def _parse_date(value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError(f"Invalid date value: {value!r}")

    def _require_date(self, params: dict[str, Any], key: str) -> date:
        value = params.get(key)
        if value is None:
            raise ValueError(f"Missing required date parameter: {key}")
        return self._parse_date(value)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    def _normalize_dates(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        for key in ("trade_date", "start_date", "end_date"):
            if key in normalized and normalized[key] is not None:
                if isinstance(normalized[key], date):
                    normalized[key] = normalized[key].isoformat()
                else:
                    normalized[key] = date.fromisoformat(str(normalized[key])).isoformat()
        return normalized
