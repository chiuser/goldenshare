from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.services.sync_v2.execution_errors import ExecutionCanceledError
from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.job_execution_step import JobExecutionStep
from src.ops.models.ops.job_execution_unit import JobExecutionUnit
from src.ops.specs import get_job_spec, get_workflow_spec
from src.app.exceptions import WebAppError
from src.ops.services.operations_history_backfill_service import HistoryBackfillService
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshService
from src.foundation.services.sync_v2.runtime_registry import build_sync_service
from src.ops.index_series_active_store_adapter import OpsIndexSeriesActiveStore
from src.ops.sync_state_store_adapter import OpsSyncJobStateStore, OpsSyncRunLogStore
from src.ops.services.job_execution_sync_context import JobExecutionSyncContext
from src.utils import truncate_text


@dataclass(slots=True)
class DispatchOutcome:
    status: str
    rows_fetched: int = 0
    rows_written: int = 0
    summary_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class OperationsDispatcher:
    MAX_ERROR_MESSAGE_LENGTH = 16_000
    MAX_EVENT_MESSAGE_LENGTH = 8_000
    MAX_STEP_MESSAGE_LENGTH = 8_000
    MAX_PROGRESS_MESSAGE_LENGTH = 1_000
    MAX_PROGRESS_PAYLOAD_BYTES = 2_048
    MAX_REASON_BUCKETS = 3
    MAX_REASON_CODE_LENGTH = 64

    def __init__(self, serving_light_refresh_service: ServingLightRefreshService | None = None) -> None:
        self.serving_light_refresh_service = serving_light_refresh_service or ServingLightRefreshService()

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
        unit = self._create_step_unit(session, execution_id=execution.id, step_id=step.id, unit_id=f"{step.step_key}:1")
        self._event(session, execution.id, "step_started", step_id=step.id, unit_id=unit.unit_id, message=job_spec.display_name)
        session.commit()
        try:
            rows_fetched, rows_written, summary_message = self._run_job(session, execution, job_spec, step.id)
            step.status = "success"
            step.ended_at = datetime.now(timezone.utc)
            step.rows_fetched = rows_fetched
            step.rows_written = rows_written
            step.message = summary_message
            step.unit_total = 1
            step.unit_done = 1
            step.unit_failed = 0
            self._finalize_step_unit(
                unit,
                status="success",
                rows_fetched=rows_fetched,
                rows_written=rows_written,
            )
            self._event(session, execution.id, "step_succeeded", step_id=step.id, unit_id=unit.unit_id, message=summary_message)
            session.commit()
            return DispatchOutcome(
                status="success",
                rows_fetched=rows_fetched,
                rows_written=rows_written,
                summary_message=summary_message,
            )
        except ExecutionCanceledError as exc:
            safe_message = self._sanitize_error_message(str(exc))
            session.rollback()
            step = session.get(JobExecutionStep, step.id)
            unit = session.get(JobExecutionUnit, unit.id) if unit is not None else None
            if step is not None:
                step.status = "canceled"
                step.ended_at = datetime.now(timezone.utc)
                step.message = self._sanitize_step_message(safe_message)
                step.unit_total = 1
                step.unit_done = 0
                step.unit_failed = 1
            if unit is not None:
                self._finalize_step_unit(unit, status="canceled", error_message=safe_message)
            self._event(
                session,
                execution.id,
                "step_canceled",
                step_id=step.id if step else None,
                unit_id=unit.unit_id if unit is not None else None,
                message=safe_message,
                level="WARNING",
            )
            session.commit()
            return DispatchOutcome(
                status="canceled",
                summary_message=safe_message,
            )
        except Exception as exc:
            safe_message = self._sanitize_error_message(str(exc))
            session.rollback()
            step = session.get(JobExecutionStep, step.id)
            unit = session.get(JobExecutionUnit, unit.id) if unit is not None else None
            if step is not None:
                step.status = "failed"
                step.ended_at = datetime.now(timezone.utc)
                step.message = self._sanitize_step_message(safe_message)
                step.unit_total = 1
                step.unit_done = 0
                step.unit_failed = 1
            if unit is not None:
                self._finalize_step_unit(unit, status="failed", error_code="execution_failed", error_message=safe_message)
            self._event(
                session,
                execution.id,
                "step_failed",
                step_id=step.id if step else None,
                unit_id=unit.unit_id if unit is not None else None,
                message=safe_message,
                level="ERROR",
            )
            session.commit()
            return DispatchOutcome(
                status="failed",
                error_code="execution_failed",
                error_message=safe_message,
                summary_message=safe_message,
            )

    def _dispatch_workflow(self, session: Session, execution: JobExecution, workflow_spec) -> DispatchOutcome:  # type: ignore[no-untyped-def]
        total_fetched = 0
        total_written = 0
        completed = 0
        last_message: str | None = None
        failed_step_keys: set[str] = set()
        had_failures = False
        for sequence_no, workflow_step in enumerate(workflow_spec.steps, start=1):
            dependency_failed = any(dep in failed_step_keys for dep in workflow_step.depends_on)
            if dependency_failed:
                step = self._create_step(
                    session,
                    execution_id=execution.id,
                    step_key=workflow_step.step_key,
                    display_name=workflow_step.display_name,
                    sequence_no=sequence_no,
                )
                step.status = "blocked"
                step.ended_at = datetime.now(timezone.utc)
                step.message = self._sanitize_step_message("依赖步骤失败，当前步骤被阻塞。")
                step.skip_reason_code = "dependency_failed"
                step.depends_on_step_keys_json = list(workflow_step.depends_on)
                step.unit_total = 0
                step.unit_done = 0
                step.unit_failed = 0
                self._event(
                    session,
                    execution.id,
                    "step_blocked",
                    step_id=step.id,
                    message=step.message,
                    level="WARNING",
                )
                session.commit()
                continue

            job_spec = get_job_spec(workflow_step.job_key)
            if job_spec is None:
                message = f"Workflow step job spec does not exist: {workflow_step.job_key}"
                self._event(session, execution.id, "failed", message=message, level="ERROR")
                session.commit()
                return DispatchOutcome(status="failed", error_code="workflow_invalid", error_message=message, summary_message=message)

            params = dict(execution.params_json or {})
            params.update(workflow_step.default_params)
            params.update(workflow_step.params_override)
            effective_failure_policy = workflow_step.failure_policy_override or workflow_spec.failure_policy_default or "fail_fast"
            step_execution = JobExecution(
                id=execution.id,
                spec_type="job",
                spec_key=job_spec.key,
                trigger_source=execution.trigger_source,
                status=execution.status,
                requested_at=execution.requested_at,
                params_json=params,
                correlation_id=execution.correlation_id,
                run_profile=execution.run_profile,
                workflow_profile=execution.workflow_profile,
            )
            step = self._create_step(
                session,
                execution_id=execution.id,
                step_key=workflow_step.step_key,
                display_name=workflow_step.display_name,
                sequence_no=sequence_no,
            )
            unit = self._create_step_unit(session, execution_id=execution.id, step_id=step.id, unit_id=f"{step.step_key}:1")
            step.depends_on_step_keys_json = list(workflow_step.depends_on)
            step.failure_policy_effective = effective_failure_policy
            self._event(session, execution.id, "step_started", step_id=step.id, unit_id=unit.unit_id, message=workflow_step.display_name)
            session.commit()
            try:
                rows_fetched, rows_written, summary_message = self._run_job(session, step_execution, job_spec, step.id)
                step.status = "success"
                step.ended_at = datetime.now(timezone.utc)
                step.rows_fetched = rows_fetched
                step.rows_written = rows_written
                step.message = summary_message
                step.unit_total = 1
                step.unit_done = 1
                step.unit_failed = 0
                self._finalize_step_unit(
                    unit,
                    status="success",
                    rows_fetched=rows_fetched,
                    rows_written=rows_written,
                )
                self._event(session, execution.id, "step_succeeded", step_id=step.id, unit_id=unit.unit_id, message=summary_message)
                session.commit()
                total_fetched += rows_fetched
                total_written += rows_written
                completed += 1
                last_message = summary_message
            except ExecutionCanceledError as exc:
                safe_message = self._sanitize_error_message(str(exc))
                session.rollback()
                step = session.get(JobExecutionStep, step.id)
                unit = session.get(JobExecutionUnit, unit.id) if unit is not None else None
                if step is not None:
                    step.status = "canceled"
                    step.ended_at = datetime.now(timezone.utc)
                    step.message = self._sanitize_step_message(safe_message)
                    step.unit_total = 1
                    step.unit_done = 0
                    step.unit_failed = 1
                if unit is not None:
                    self._finalize_step_unit(unit, status="canceled", error_message=safe_message)
                self._event(
                    session,
                    execution.id,
                    "step_canceled",
                    step_id=step.id if step else None,
                    unit_id=unit.unit_id if unit is not None else None,
                    message=safe_message,
                    level="WARNING",
                )
                session.commit()
                return DispatchOutcome(
                    status="canceled",
                    rows_fetched=total_fetched,
                    rows_written=total_written,
                    summary_message=safe_message,
                )
            except Exception as exc:
                safe_message = self._sanitize_error_message(str(exc))
                session.rollback()
                step = session.get(JobExecutionStep, step.id)
                unit = session.get(JobExecutionUnit, unit.id) if unit is not None else None
                if step is not None:
                    step.status = "failed"
                    step.ended_at = datetime.now(timezone.utc)
                    step.message = self._sanitize_step_message(safe_message)
                    step.failure_policy_effective = effective_failure_policy
                    step.unit_total = 1
                    step.unit_done = 0
                    step.unit_failed = 1
                if unit is not None:
                    self._finalize_step_unit(unit, status="failed", error_code="workflow_step_failed", error_message=safe_message)
                self._event(
                    session,
                    execution.id,
                    "step_failed",
                    step_id=step.id if step else None,
                    unit_id=unit.unit_id if unit is not None else None,
                    message=safe_message,
                    level="ERROR",
                )
                session.commit()
                had_failures = True
                failed_step_keys.add(workflow_step.step_key)
                last_message = safe_message
                if effective_failure_policy == "continue_on_error":
                    continue
                return DispatchOutcome(
                    status="partial_success" if completed else "failed",
                    rows_fetched=total_fetched,
                    rows_written=total_written,
                    summary_message=safe_message,
                    error_code="workflow_step_failed",
                    error_message=safe_message,
                )

        final_status = "partial_success" if had_failures else "success"
        return DispatchOutcome(
            status=final_status,
            rows_fetched=total_fetched,
            rows_written=total_written,
            summary_message=last_message or workflow_spec.display_name,
            error_code="workflow_step_failed" if had_failures else None,
            error_message=last_message if had_failures else None,
        )

    def _run_job(self, session: Session, execution: JobExecution, job_spec, step_id: int) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        params = dict(execution.params_json or {})
        if job_spec.executor_kind == "sync_service":
            return self._run_sync_job(session, execution, job_spec, params, step_id=step_id)
        if job_spec.executor_kind == "history_backfill_service":
            return self._run_backfill_job(session, execution, job_spec, params, step_id)
        if job_spec.executor_kind == "maintenance":
            return self._run_maintenance_job(session, job_spec, params)
        raise ValueError(f"Unsupported executor kind: {job_spec.executor_kind}")

    def _run_sync_job(
        self,
        session: Session,
        execution: JobExecution,
        job_spec,
        params: dict[str, Any],
        *,
        step_id: int | None = None,
    ) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        _, resource = job_spec.key.split(".", 1)
        normalized_params = self._normalize_dates(params)
        parsed_trade_date: date | None = None
        execution_context = JobExecutionSyncContext(session)
        run_log_store = OpsSyncRunLogStore(session)
        job_state_store = OpsSyncJobStateStore(session)
        index_series_active_store = OpsIndexSeriesActiveStore(session)
        if job_spec.category == "sync_daily":
            service = build_sync_service(
                resource,
                session,
                execution_context=execution_context,
                run_log_store=run_log_store,
                job_state_store=job_state_store,
                index_series_active_store=index_series_active_store,
            )
            supported_param_keys = {param.key for param in (job_spec.supported_params or ())}
            if "month" in supported_param_keys and "trade_date" not in supported_param_keys:
                result = service.run_incremental(execution_id=execution.id, **normalized_params)
            else:
                trade_date = normalized_params.get("trade_date")
                if not trade_date:
                    trade_date = self._resolve_default_trade_date(session)
                if not trade_date:
                    raise ValueError("未找到可用交易日，请先同步交易日历或手动指定日期。")
                parsed_trade_date = self._parse_date(trade_date) if trade_date else None
                if parsed_trade_date and self._is_closed_trade_date(session, parsed_trade_date):
                    summary = f"skip {job_spec.key} trade_date={parsed_trade_date.isoformat()} 非交易日"
                    return 0, 0, summary
                extra_params = {key: value for key, value in normalized_params.items() if key != "trade_date"}
                result = service.run_incremental(trade_date=parsed_trade_date, execution_id=execution.id, **extra_params)
        else:
            service = build_sync_service(
                resource,
                session,
                execution_context=execution_context,
                run_log_store=run_log_store,
                job_state_store=job_state_store,
                index_series_active_store=index_series_active_store,
            )
            result = service.run_full(execution_id=execution.id, **normalized_params)

        light_note = self._refresh_serving_light_if_needed(
            session,
            execution_id=execution.id,
            step_id=step_id,
            resource=resource,
            rows_written=int(result.rows_written or 0),
            trade_date=parsed_trade_date,
            start_date=self._optional_date(normalized_params.get("start_date")),
            end_date=self._optional_date(normalized_params.get("end_date")),
            ts_code=self._normalize_single_ts_code(normalized_params.get("ts_code")),
        )
        summary_message = result.message
        if light_note:
            summary_message = f"{summary_message}；{light_note}" if summary_message else light_note
        return result.rows_fetched, result.rows_written, summary_message

    def _run_backfill_job(
        self,
        session: Session,
        execution: JobExecution,
        job_spec,
        params: dict[str, Any],
        step_id: int,
    ) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        service = HistoryBackfillService(
            session,
            execution_context=JobExecutionSyncContext(session),
            run_log_store=OpsSyncRunLogStore(session),
            job_state_store=OpsSyncJobStateStore(session),
            index_series_active_store=OpsIndexSeriesActiveStore(session),
        )
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
                exchange_id=normalized.get("exchange_id"),
                ts_code=normalized.get("ts_code"),
                con_code=normalized.get("con_code"),
                idx_type=normalized.get("idx_type"),
                market=normalized.get("market"),
                hot_type=normalized.get("hot_type"),
                is_new=normalized.get("is_new"),
                suspend_type=normalized.get("suspend_type"),
                content_type=normalized.get("content_type"),
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
        elif job_spec.category == "backfill_by_month":
            summary = service.backfill_by_months(
                resource=resource,
                start_month=self._require_value(normalized, "start_month"),
                end_month=self._require_value(normalized, "end_month"),
                offset=int(normalized.get("offset", 0)),
                limit=self._optional_int(normalized.get("limit")),
                progress=on_progress,
                execution_id=execution.id,
            )
        else:
            raise ValueError(f"Unsupported backfill category: {job_spec.category}")

        light_note = self._refresh_serving_light_if_needed(
            session,
            execution_id=execution.id,
            step_id=step_id,
            resource=resource,
            rows_written=int(summary.rows_written or 0),
            start_date=self._optional_date(normalized.get("start_date")),
            end_date=self._optional_date(normalized.get("end_date")),
            ts_code=self._normalize_single_ts_code(normalized.get("ts_code")),
        )
        summary_message = f"units={summary.units_processed}"
        if light_note:
            summary_message = f"{summary_message}；{light_note}"
        return summary.rows_fetched, summary.rows_written, summary_message

    def _run_maintenance_job(self, session: Session, job_spec, params: dict[str, Any]) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        if job_spec.key == "maintenance.rebuild_dm":
            session.execute(text("REFRESH MATERIALIZED VIEW dm.equity_daily_snapshot"))
            session.commit()
            return 0, 0, "materialized view refreshed"
        if job_spec.key == "maintenance.rebuild_index_kline_serving":
            start_date = self._resolve_maintenance_start_date(params)
            end_date = self._resolve_maintenance_end_date(params)
            if start_date > end_date:
                raise ValueError("start_date cannot be greater than end_date")
            weekly_rows = self._rebuild_index_period_serving(
                session=session,
                target_table="core_serving.index_weekly_serving",
                start_date=start_date,
                end_date=end_date,
                period_granularity="week",
            )
            monthly_rows = self._rebuild_index_period_serving(
                session=session,
                target_table="core_serving.index_monthly_serving",
                start_date=start_date,
                end_date=end_date,
                period_granularity="month",
            )
            session.commit()
            written = weekly_rows + monthly_rows
            return 0, written, f"index serving rebuilt weekly={weekly_rows} monthly={monthly_rows}"
        raise ValueError(f"Unsupported maintenance job: {job_spec.key}")

    def _rebuild_index_period_serving(
        self,
        *,
        session: Session,
        target_table: str,
        start_date: date,
        end_date: date,
        period_granularity: str,
    ) -> int:
        if period_granularity == "week":
            calendar_period_expr = "date_trunc('week', trade_date)::date"
            daily_period_expr = "date_trunc('week', d.trade_date)::date"
        elif period_granularity == "month":
            calendar_period_expr = "date_trunc('month', trade_date)::date"
            daily_period_expr = "date_trunc('month', d.trade_date)::date"
        else:
            raise ValueError(f"Unsupported period granularity: {period_granularity}")

        # Rebuild is derived-from-daily only for this date window; clear old derived rows
        # first so dual unique keys (ts_code, trade_date) / (ts_code, period_start_date)
        # won't conflict with stale non-api rows.
        session.execute(
            text(
                f"""
                delete from {target_table}
                where source <> 'api'
                  and trade_date between :start_date and :end_date
                """
            ),
            {"start_date": start_date, "end_date": end_date},
        )

        sql = text(
            f"""
            with calendar_periods as (
                select
                    {calendar_period_expr} as natural_period_start,
                    min(trade_date) as period_start_date
                from core_serving.trade_calendar
                where exchange = :exchange
                  and is_open is true
                  and trade_date between :start_date and :end_date
                group by {calendar_period_expr}
            ),
            daily_scope as (
                select
                    d.ts_code,
                    d.trade_date,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.pre_close,
                    d.vol,
                    d.amount,
                    cp.period_start_date as period_start_date
                from core_serving.index_daily_serving d
                join core_serving.index_basic b on b.ts_code = d.ts_code
                join calendar_periods cp on cp.natural_period_start = {daily_period_expr}
                where d.trade_date between :start_date and :end_date
            ),
            win as (
                select
                    ds.*,
                    row_number() over (
                        partition by ds.ts_code, ds.period_start_date
                        order by ds.trade_date asc
                    ) as rn_first,
                    row_number() over (
                        partition by ds.ts_code, ds.period_start_date
                        order by ds.trade_date desc
                    ) as rn_last
                from daily_scope ds
            ),
            agg as (
                select
                    ts_code,
                    period_start_date,
                    max(trade_date) as trade_date,
                    max(case when rn_first = 1 then open end) as open,
                    max(high) as high,
                    min(low) as low,
                    max(case when rn_last = 1 then close end) as close,
                    max(case when rn_first = 1 then pre_close end) as pre_close,
                    sum(vol) as vol,
                    sum(amount) as amount
                from win
                group by ts_code, period_start_date
            )
            insert into {target_table} (
                ts_code,
                period_start_date,
                trade_date,
                open,
                high,
                low,
                close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount,
                source
            )
            select
                a.ts_code,
                a.period_start_date,
                a.trade_date,
                a.open,
                a.high,
                a.low,
                a.close,
                a.pre_close,
                case when a.pre_close is null or a.close is null then null else a.close - a.pre_close end as change_amount,
                case
                    when a.pre_close is null or a.pre_close = 0 or a.close is null then null
                    else round(((a.close / a.pre_close) - 1) * 100, 4)
                end as pct_chg,
                a.vol,
                a.amount,
                'derived_daily'
            from agg a
            left join {target_table} existing_trade
              on existing_trade.ts_code = a.ts_code
             and existing_trade.trade_date = a.trade_date
             and existing_trade.period_start_date <> a.period_start_date
             and existing_trade.source = 'api'
            where existing_trade.ts_code is null
            on conflict (ts_code, period_start_date) do update
            set
                period_start_date = excluded.period_start_date,
                trade_date = excluded.trade_date,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                pre_close = excluded.pre_close,
                change_amount = excluded.change_amount,
                pct_chg = excluded.pct_chg,
                vol = excluded.vol,
                amount = excluded.amount,
                source = excluded.source,
                updated_at = now()
            where {target_table}.source <> 'api'
            """
        )
        result = session.execute(
            sql,
            {
                "start_date": start_date,
                "end_date": end_date,
                "exchange": get_settings().default_exchange,
            },
        )
        return result.rowcount or 0

    @staticmethod
    def _resolve_maintenance_start_date(params: dict[str, Any]) -> date:
        value = params.get("start_date")
        if value is not None:
            return OperationsDispatcher._parse_date(value)
        return date.fromisoformat(get_settings().history_start_date)

    @staticmethod
    def _resolve_maintenance_end_date(params: dict[str, Any]) -> date:
        value = params.get("end_date")
        if value is not None:
            return OperationsDispatcher._parse_date(value)
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()

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
    def _create_step_unit(
        session: Session,
        *,
        execution_id: int,
        step_id: int,
        unit_id: str,
    ) -> JobExecutionUnit:
        unit = JobExecutionUnit(
            execution_id=execution_id,
            step_id=step_id,
            unit_id=unit_id,
            status="running",
            attempt=0,
            retryable=False,
            started_at=datetime.now(timezone.utc),
            unit_payload_json={},
        )
        session.add(unit)
        session.flush()
        return unit

    @staticmethod
    def _finalize_step_unit(
        unit: JobExecutionUnit | None,
        *,
        status: str,
        rows_fetched: int = 0,
        rows_written: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if unit is None:
            return
        ended_at = datetime.now(timezone.utc)
        started_at = unit.started_at or ended_at
        unit.status = status
        unit.rows_fetched = rows_fetched
        unit.rows_written = rows_written
        unit.error_code = error_code
        unit.error_message = error_message
        unit.ended_at = ended_at
        unit.duration_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)

    def _event(
        self,
        session: Session,
        execution_id: int,
        event_type: str,
        *,
        step_id: int | None = None,
        unit_id: str | None = None,
        level: str = "INFO",
        message: str | None = None,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        execution = session.get(JobExecution, execution_id)
        correlation_id = execution.correlation_id if execution is not None else None
        dedupe_key = None
        if payload_json:
            dedupe_key = str(payload_json.get("dedupe_key") or "") or None
        if dedupe_key is None:
            dedupe_key = f"{execution_id}:{step_id or 0}:{event_type}:{uuid4().hex[:8]}"
        session.add(
            JobExecutionEvent(
                execution_id=execution_id,
                step_id=step_id,
                event_type=event_type,
                level=level,
                message=truncate_text(message, OperationsDispatcher.MAX_EVENT_MESSAGE_LENGTH),
                payload_json=payload_json or {},
                occurred_at=datetime.now(timezone.utc),
                event_id=uuid4().hex,
                event_version=1,
                correlation_id=correlation_id,
                unit_id=unit_id,
                dedupe_key=dedupe_key,
                producer="runtime",
            )
        )

    def _update_execution_progress(self, session: Session, execution_id: int, payload_json: dict[str, Any]) -> None:
        execution = session.get(JobExecution, execution_id)
        if execution is None:
            return
        execution.progress_message = truncate_text(
            str(payload_json.get("progress_message") or execution.progress_message or ""),
            self.MAX_PROGRESS_MESSAGE_LENGTH,
        )
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

    @classmethod
    def _build_progress_payload(cls, message: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"progress_message": message}
        match = re.search(r"(\d+)\s*/\s*(\d+)", message)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            payload["progress_current"] = current
            payload["progress_total"] = total
            payload["progress_percent"] = 0 if total <= 0 else round(current / total * 100)

        kv_pairs = dict(re.findall(r"([a-zA-Z_]+)=([^\s]+)", message))
        rows_fetched = cls._safe_int(kv_pairs.get("fetched"))
        rows_written = cls._safe_int(kv_pairs.get("written"))
        rows_rejected = cls._safe_int(kv_pairs.get("rejected"))

        if rows_fetched is not None:
            payload["rows_fetched"] = rows_fetched
        if rows_written is not None:
            payload["rows_written"] = rows_written
        if rows_rejected is None and rows_fetched is not None and rows_written is not None:
            rows_rejected = max(rows_fetched - rows_written, 0)
        if rows_rejected is not None:
            payload["rows_rejected"] = max(rows_rejected, 0)

        reasons_token = kv_pairs.get("reasons")
        if reasons_token:
            parsed_reason_counts = cls._parse_reasons_token(reasons_token)
            if parsed_reason_counts:
                limited_reason_counts, bucket_truncated = cls._limit_reason_counts(parsed_reason_counts)
                payload["rejected_reason_counts"] = limited_reason_counts
                payload["rows_rejected"] = max(
                    int(payload.get("rows_rejected") or 0),
                    sum(limited_reason_counts.values()),
                )
                message_marked_truncated = kv_pairs.get("reason_stats_truncated") == "1"
                payload["reason_stats_truncated"] = bool(message_marked_truncated or bucket_truncated)
                payload["reason_stats_truncate_note"] = (
                    "拒绝原因过多，仅展示 Top3。"
                    if payload["reason_stats_truncated"]
                    else None
                )

        return cls._enforce_progress_payload_limit(payload)

    @classmethod
    def _parse_reasons_token(cls, token: str) -> dict[str, int]:
        parsed: dict[str, int] = {}
        for chunk in token.split("|"):
            chunk_text = str(chunk or "").strip()
            if not chunk_text or ":" not in chunk_text:
                continue
            code_text, count_text = chunk_text.rsplit(":", 1)
            code = str(code_text).strip()[: cls.MAX_REASON_CODE_LENGTH]
            if not code:
                continue
            count = cls._safe_int(count_text)
            if count is None or count <= 0:
                continue
            parsed[code] = parsed.get(code, 0) + count
        return parsed

    @classmethod
    def _limit_reason_counts(cls, reason_counts: dict[str, int]) -> tuple[dict[str, int], bool]:
        ordered = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        truncated = len(ordered) > cls.MAX_REASON_BUCKETS
        limited = ordered[: cls.MAX_REASON_BUCKETS]
        return dict(limited), truncated

    @classmethod
    def _enforce_progress_payload_limit(cls, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        if cls._payload_size_bytes(result) <= cls.MAX_PROGRESS_PAYLOAD_BYTES:
            return result

        if "reason_stats_truncate_note" in result:
            result["reason_stats_truncate_note"] = "原因信息过长，已截断。"
        if cls._payload_size_bytes(result) <= cls.MAX_PROGRESS_PAYLOAD_BYTES:
            return result

        reason_counts = result.get("rejected_reason_counts")
        if isinstance(reason_counts, dict) and len(reason_counts) > 1:
            top_reason, top_count = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[0]
            result["rejected_reason_counts"] = {top_reason: top_count}
            result["reason_stats_truncated"] = True
            result["reason_stats_truncate_note"] = "原因信息过长，仅展示首个原因。"
        if cls._payload_size_bytes(result) <= cls.MAX_PROGRESS_PAYLOAD_BYTES:
            return result

        result.pop("rejected_reason_counts", None)
        result["reason_stats_truncated"] = True
        result["reason_stats_truncate_note"] = "原因信息过长，仅保留拒绝总数。"
        if cls._payload_size_bytes(result) <= cls.MAX_PROGRESS_PAYLOAD_BYTES:
            return result

        result.pop("reason_stats_truncate_note", None)
        result.pop("rows_fetched", None)
        result.pop("rows_written", None)
        return result

    @staticmethod
    def _payload_size_bytes(payload: dict[str, Any]) -> int:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _sanitize_error_message(cls, message: str | None) -> str | None:
        return truncate_text(message, cls.MAX_ERROR_MESSAGE_LENGTH)

    @classmethod
    def _sanitize_step_message(cls, message: str | None) -> str | None:
        return truncate_text(message, cls.MAX_STEP_MESSAGE_LENGTH)

    @staticmethod
    def _parse_date(value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError(f"Invalid date value: {value!r}")

    @staticmethod
    def _resolve_default_trade_date(session: Session) -> date | None:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        stmt = (
            select(TradeCalendar.trade_date)
            .where(TradeCalendar.is_open.is_(True))
            .where(TradeCalendar.trade_date <= today)
            .order_by(TradeCalendar.trade_date.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def _require_date(self, params: dict[str, Any], key: str) -> date:
        value = params.get(key)
        if value is None:
            raise ValueError(f"Missing required date parameter: {key}")
        return self._parse_date(value)

    @staticmethod
    def _is_closed_trade_date(session: Session, trade_date: date) -> bool:
        exchange = get_settings().default_exchange
        stmt = (
            select(TradeCalendar.is_open)
            .where(TradeCalendar.exchange == exchange)
            .where(TradeCalendar.trade_date == trade_date)
            .limit(1)
        )
        is_open = session.scalar(stmt)
        return is_open is False

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _optional_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @staticmethod
    def _normalize_single_ts_code(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().upper()
            return normalized or None
        if isinstance(value, list | tuple):
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @staticmethod
    def _require_value(params: dict[str, Any], key: str) -> str:
        value = params.get(key)
        if value in (None, ""):
            raise ValueError(f"{key} is required")
        return str(value)

    def _normalize_dates(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        for key in ("trade_date", "start_date", "end_date"):
            if key in normalized and normalized[key] is not None:
                if isinstance(normalized[key], date):
                    normalized[key] = normalized[key].isoformat()
                else:
                    normalized[key] = date.fromisoformat(str(normalized[key])).isoformat()
        return normalized

    def _refresh_serving_light_if_needed(
        self,
        session: Session,
        *,
        execution_id: int,
        step_id: int | None,
        resource: str,
        rows_written: int,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
    ) -> str | None:
        if resource != "daily":
            return None
        if rows_written <= 0:
            message = "轻量层刷新跳过：本次写入 0 行。"
            self._event(
                session,
                execution_id,
                "serving_light_refresh_skipped",
                step_id=step_id,
                level="INFO",
                message=message,
                payload_json={"resource": resource, "rows_written": rows_written},
            )
            return "轻量层刷新已跳过"

        effective_start_date = start_date or trade_date
        effective_end_date = end_date or trade_date
        if effective_start_date is not None and effective_end_date is not None and effective_start_date > effective_end_date:
            effective_start_date, effective_end_date = effective_end_date, effective_start_date

        try:
            refresh_result = self.serving_light_refresh_service.refresh_equity_daily_bar(
                session,
                start_date=effective_start_date,
                end_date=effective_end_date,
                ts_code=ts_code,
                commit=False,
            )
            message = f"轻量层刷新完成：{refresh_result.touched_rows} 行。"
            self._event(
                session,
                execution_id,
                "serving_light_refreshed",
                step_id=step_id,
                level="INFO",
                message=message,
                payload_json={
                    "resource": resource,
                    "rows_written": rows_written,
                    "touched_rows": refresh_result.touched_rows,
                    "start_date": effective_start_date.isoformat() if effective_start_date else None,
                    "end_date": effective_end_date.isoformat() if effective_end_date else None,
                    "ts_code": ts_code,
                },
            )
            return message
        except Exception as exc:  # pragma: no cover - defensive
            message = f"轻量层刷新失败：{exc}"
            self._event(
                session,
                execution_id,
                "serving_light_refresh_failed",
                step_id=step_id,
                level="WARNING",
                message=message,
                payload_json={
                    "resource": resource,
                    "rows_written": rows_written,
                    "start_date": effective_start_date.isoformat() if effective_start_date else None,
                    "end_date": effective_end_date.isoformat() if effective_end_date else None,
                    "ts_code": ts_code,
                },
            )
            return message
