from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.models.core.trade_calendar import TradeCalendar
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
            return self._run_maintenance_job(session, job_spec, params)
        raise ValueError(f"Unsupported executor kind: {job_spec.executor_kind}")

    def _run_sync_job(self, session: Session, execution: JobExecution, job_spec, params: dict[str, Any]) -> tuple[int, int, str | None]:  # type: ignore[no-untyped-def]
        _, resource = job_spec.key.split(".", 1)
        normalized_params = self._normalize_dates(params)
        if job_spec.category == "sync_daily":
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
            service = build_sync_service(resource, session)
            result = service.run_incremental(trade_date=parsed_trade_date, execution_id=execution.id, **extra_params)
        else:
            service = build_sync_service(resource, session)
            result = service.run_full(execution_id=execution.id, **normalized_params)
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
                target_table="core.index_weekly_serving",
                start_date=start_date,
                end_date=end_date,
                period_granularity="week",
            )
            monthly_rows = self._rebuild_index_period_serving(
                session=session,
                target_table="core.index_monthly_serving",
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
                from core.trade_calendar
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
                from core.index_daily_serving d
                join core.index_basic b on b.ts_code = d.ts_code
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

    def _normalize_dates(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        for key in ("trade_date", "start_date", "end_date"):
            if key in normalized and normalized[key] is not None:
                if isinstance(normalized[key], date):
                    normalized[key] = normalized[key].isoformat()
                else:
                    normalized[key] = date.fromisoformat(str(normalized[key])).isoformat()
        return normalized
