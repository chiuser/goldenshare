from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.services.sync_v2.contracts import PlanUnit
from src.foundation.services.sync_v2.execution_errors import ExecutionCanceledError
from src.foundation.services.sync_v2.runtime_registry import build_sync_service
from src.foundation.services.sync_v2.sync_state_store import NullSyncJobStateStore, NullSyncRunRecorder
from src.ops.index_series_active_store_adapter import OpsIndexSeriesActiveStore
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshService
from src.ops.services.task_run_sync_context import TaskRunSyncContext
from src.ops.specs import get_job_spec, get_workflow_spec
from src.utils import truncate_text


@dataclass(slots=True)
class TaskRunDispatchOutcome:
    status: str
    rows_fetched: int = 0
    rows_saved: int = 0
    rows_rejected: int = 0
    summary_message: str | None = None
    issue_id: int | None = None
    status_reason_code: str | None = None


class TaskRunDispatcher:
    MAX_TECHNICAL_MESSAGE_LENGTH = 32_000
    MAX_OPERATOR_MESSAGE_LENGTH = 1_000

    def __init__(self, serving_light_refresh_service: ServingLightRefreshService | None = None) -> None:
        self.serving_light_refresh_service = serving_light_refresh_service or ServingLightRefreshService()

    def dispatch(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        if task_run.task_type == "dataset_action":
            return self._dispatch_dataset_action(session, task_run)
        if task_run.task_type == "workflow":
            return self._dispatch_workflow(session, task_run)
        if task_run.task_type == "system_job":
            return self._dispatch_system_job(session, task_run)
        raise WebAppError(status_code=422, code="validation_error", message="Unsupported task_type")

    def _dispatch_dataset_action(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        action_request = self._prepare_dataset_action_request(session, self._build_dataset_action_request(task_run))
        plan = DatasetActionResolver(session).build_plan(action_request)
        node = self._create_node(
            session,
            task_run_id=task_run.id,
            node_key=plan.plan_id,
            node_type="dataset_plan",
            sequence_no=1,
            title=f"维护 {task_run.title}",
            resource_key=plan.dataset_key,
            time_input=dict(task_run.time_input_json or {}),
            context={"run_profile": plan.run_profile},
        )
        task_run.current_node_id = node.id
        task_run.unit_total = int(plan.planning.unit_count or len(plan.units))
        task_run.plan_snapshot_json = self._plan_snapshot(plan)
        session.commit()
        try:
            rows_fetched, rows_saved, rows_rejected, summary_message = self._run_dataset_action_plan(
                session,
                task_run,
                action_request,
                plan,
            )
            self._finish_node(
                node,
                status="success",
                rows_fetched=rows_fetched,
                rows_saved=rows_saved,
                rows_rejected=rows_rejected,
            )
            task_run.unit_done = task_run.unit_total
            task_run.unit_failed = 0
            task_run.progress_percent = 100
            session.commit()
            return TaskRunDispatchOutcome(
                status="success",
                rows_fetched=rows_fetched,
                rows_saved=rows_saved,
                rows_rejected=rows_rejected,
                summary_message=summary_message,
            )
        except ExecutionCanceledError as exc:
            session.rollback()
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=node.id,
                code="execution_canceled",
                title="任务已停止",
                operator_message="任务已收到停止请求，并在当前处理边界结束。",
                suggested_action="如仍需处理，请重新提交任务。",
                technical_message=str(exc),
                source_phase="execute",
                severity="warning",
            )
            node = session.get(TaskRunNode, node.id)
            if node is not None:
                node.issue_id = issue.id
                self._finish_node(node, status="canceled")
            session.commit()
            return TaskRunDispatchOutcome(status="canceled", summary_message=issue.operator_message, issue_id=issue.id)
        except Exception as exc:
            session.rollback()
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=node.id,
                code="execution_failed",
                title="任务处理失败",
                operator_message="任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
                suggested_action="先确认已保存数据和失败位置，再决定是否缩小范围重新提交。",
                technical_message=str(exc),
                source_phase="execute",
                severity="error",
            )
            node = session.get(TaskRunNode, node.id)
            if node is not None:
                node.issue_id = issue.id
                self._finish_node(node, status="failed")
            session.commit()
            return TaskRunDispatchOutcome(
                status="failed",
                summary_message=issue.operator_message,
                issue_id=issue.id,
                status_reason_code=issue.code,
            )

    def _dispatch_workflow(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        spec_key = str((task_run.request_payload_json or {}).get("spec_key") or "")
        workflow_spec = get_workflow_spec(spec_key)
        if workflow_spec is None:
            raise WebAppError(status_code=404, code="not_found", message="Workflow spec does not exist")

        total_fetched = 0
        total_saved = 0
        total_rejected = 0
        completed = 0
        failed = 0
        last_issue_id: int | None = None
        last_message: str | None = None
        for sequence_no, workflow_step in enumerate(workflow_spec.steps, start=1):
            params = dict(task_run.request_payload_json or {})
            params.update(workflow_step.default_params)
            params.update(workflow_step.params_override)
            step_resource_key = workflow_step.dataset_key or self._resource_key_from_spec_key(workflow_step.job_key)
            node = self._create_node(
                session,
                task_run_id=task_run.id,
                node_key=workflow_step.step_key,
                node_type="workflow_step",
                sequence_no=sequence_no,
                title=workflow_step.display_name,
                resource_key=step_resource_key,
                time_input=dict(task_run.time_input_json or {}),
                context={"job_key": workflow_step.job_key},
            )
            task_run.current_node_id = node.id
            session.commit()
            try:
                if workflow_step.job_key.endswith(".maintain"):
                    step_run = self._step_task_run(task_run, workflow_step.job_key, step_resource_key, params)
                    request = self._prepare_dataset_action_request(session, self._build_dataset_action_request(step_run))
                    plan = DatasetActionResolver(session).build_plan(request)
                    rows_fetched, rows_saved, rows_rejected, message = self._run_dataset_action_plan(session, step_run, request, plan)
                else:
                    job_spec = get_job_spec(workflow_step.job_key)
                    if job_spec is None:
                        raise ValueError(f"Workflow step job spec does not exist: {workflow_step.job_key}")
                    rows_fetched, rows_saved, message = self._run_maintenance_job(session, job_spec, params)
                    rows_rejected = max(rows_fetched - rows_saved, 0)
                self._finish_node(
                    node,
                    status="success",
                    rows_fetched=rows_fetched,
                    rows_saved=rows_saved,
                    rows_rejected=rows_rejected,
                )
                total_fetched += rows_fetched
                total_saved += rows_saved
                total_rejected += rows_rejected
                completed += 1
                last_message = message
                session.commit()
            except Exception as exc:
                session.rollback()
                failed += 1
                issue = self._record_issue(
                    session,
                    task_run=task_run,
                    node_id=node.id,
                    code="workflow_step_failed",
                    title="工作流步骤失败",
                    operator_message=f"{workflow_step.display_name} 处理失败。",
                    suggested_action="查看技术诊断，确认失败步骤后再决定是否重新提交。",
                    technical_message=str(exc),
                    source_phase="execute",
                    severity="error",
                )
                node = session.get(TaskRunNode, node.id)
                if node is not None:
                    node.issue_id = issue.id
                    self._finish_node(node, status="failed")
                session.commit()
                last_issue_id = issue.id
                last_message = issue.operator_message
                if (workflow_step.failure_policy_override or workflow_spec.failure_policy_default) != "continue_on_error":
                    break

        task_run.unit_total = len(workflow_spec.steps)
        task_run.unit_done = completed
        task_run.unit_failed = failed
        task_run.progress_percent = int((completed + failed) / len(workflow_spec.steps) * 100) if workflow_spec.steps else 100
        status = "partial_success" if completed and failed else ("failed" if failed else "success")
        return TaskRunDispatchOutcome(
            status=status,
            rows_fetched=total_fetched,
            rows_saved=total_saved,
            rows_rejected=total_rejected,
            summary_message=last_message or workflow_spec.display_name,
            issue_id=last_issue_id,
            status_reason_code="workflow_step_failed" if failed else None,
        )

    def _dispatch_system_job(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        spec_key = str((task_run.request_payload_json or {}).get("spec_key") or "")
        job_spec = get_job_spec(spec_key)
        if job_spec is None:
            raise WebAppError(status_code=404, code="not_found", message="Job spec does not exist")
        node = self._create_node(
            session,
            task_run_id=task_run.id,
            node_key=spec_key,
            node_type="system_action",
            sequence_no=1,
            title=job_spec.display_name,
            resource_key=task_run.resource_key,
            time_input=dict(task_run.time_input_json or {}),
            context={"job_key": spec_key},
        )
        task_run.current_node_id = node.id
        session.commit()
        try:
            rows_fetched, rows_saved, message = self._run_maintenance_job(session, job_spec, dict(task_run.request_payload_json or {}))
            rows_rejected = max(rows_fetched - rows_saved, 0)
            self._finish_node(node, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved, rows_rejected=rows_rejected)
            session.commit()
            return TaskRunDispatchOutcome(
                status="success",
                rows_fetched=rows_fetched,
                rows_saved=rows_saved,
                rows_rejected=rows_rejected,
                summary_message=message,
            )
        except Exception as exc:
            session.rollback()
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=node.id,
                code="system_job_failed",
                title="系统维护失败",
                operator_message="系统维护动作执行失败。",
                suggested_action="查看技术诊断并确认是否需要重新提交。",
                technical_message=str(exc),
                source_phase="execute",
                severity="error",
            )
            node = session.get(TaskRunNode, node.id)
            if node is not None:
                node.issue_id = issue.id
                self._finish_node(node, status="failed")
            session.commit()
            return TaskRunDispatchOutcome(status="failed", summary_message=issue.operator_message, issue_id=issue.id)

    def _run_dataset_action_plan(
        self,
        session: Session,
        task_run: TaskRun,
        action_request: DatasetActionRequest,
        plan,
    ) -> tuple[int, int, int, str | None]:  # type: ignore[no-untyped-def]
        service = build_sync_service(
            plan.dataset_key,
            session,
            execution_context=TaskRunSyncContext(session),
            run_recorder=NullSyncRunRecorder(),
            job_state_store=NullSyncJobStateStore(),
            index_series_active_store=OpsIndexSeriesActiveStore(session),
        )
        filters = dict(action_request.filters or {})
        time_input = action_request.time_input
        parsed_trade_date: date | None = None
        if plan.run_profile == "point_incremental":
            parsed_trade_date = time_input.trade_date or self._resolve_default_trade_date(session)
            if parsed_trade_date is None:
                raise ValueError("未找到可用日期，请先同步日历或手动指定日期。")
            if not time_input.month and self._is_closed_trade_date(session, parsed_trade_date):
                return 0, 0, 0, f"skip {plan.dataset_key} trade_date={parsed_trade_date.isoformat()} 非交易日"
            extra_params = dict(filters)
            if time_input.month:
                extra_params["month"] = time_input.month
            result = service.run_incremental(
                trade_date=parsed_trade_date,
                execution_id=task_run.id,
                _plan_units=self._plan_units_from_snapshot(plan),
                **extra_params,
            )
        elif plan.run_profile == "range_rebuild":
            if time_input.start_date is None or time_input.end_date is None:
                raise ValueError("range maintain requires start_date and end_date")
            result = service.run_full(
                execution_id=task_run.id,
                run_profile="range_rebuild",
                start_date=time_input.start_date,
                end_date=time_input.end_date,
                _plan_units=self._plan_units_from_snapshot(plan),
                **filters,
            )
        else:
            result = service.run_full(
                execution_id=task_run.id,
                run_profile="snapshot_refresh",
                _plan_units=self._plan_units_from_snapshot(plan),
                **filters,
            )

        rows_fetched = int(result.rows_fetched or 0)
        rows_saved = int(result.rows_written or 0)
        rows_rejected = max(rows_fetched - rows_saved, 0)
        light_note = self._refresh_serving_light_if_needed(
            session,
            task_run_id=task_run.id,
            resource=plan.dataset_key,
            rows_saved=rows_saved,
            trade_date=parsed_trade_date,
            start_date=time_input.start_date,
            end_date=time_input.end_date,
            ts_code=self._normalize_single_ts_code(filters.get("ts_code")),
        )
        summary_message = str(result.message or "").strip() or f"units={plan.planning.unit_count}"
        if light_note:
            summary_message = f"{summary_message}；{light_note}"
        return rows_fetched, rows_saved, rows_rejected, summary_message

    def _build_dataset_action_request(self, task_run: TaskRun) -> DatasetActionRequest:
        time_payload = dict(task_run.time_input_json or {})
        filters = dict(task_run.filters_json or {})
        resource_key = str(task_run.resource_key or "").strip()
        if not resource_key:
            raise ValueError("resource_key is required")
        return DatasetActionRequest(
            dataset_key=resource_key,
            action=str(task_run.action or "maintain").strip() or "maintain",
            time_input=DatasetTimeInput(
                mode=str(time_payload.get("mode") or "none").strip() or "none",
                trade_date=self._optional_date(time_payload.get("trade_date")),
                start_date=self._optional_date(time_payload.get("start_date")),
                end_date=self._optional_date(time_payload.get("end_date")),
                month=self._optional_text(time_payload.get("month")),
                start_month=self._optional_text(time_payload.get("start_month")),
                end_month=self._optional_text(time_payload.get("end_month")),
                date_field=self._optional_text(time_payload.get("date_field")),
            ),
            filters=filters,
            trigger_source=task_run.trigger_source,
            requested_by_user_id=task_run.requested_by_user_id,
            schedule_id=task_run.schedule_id,
            execution_id=task_run.id,
        )

    def _prepare_dataset_action_request(self, session: Session, request: DatasetActionRequest) -> DatasetActionRequest:
        time_input = request.time_input
        if time_input.mode != "point" or time_input.trade_date is not None or time_input.month:
            return request
        trade_date = self._resolve_default_trade_date(session)
        if trade_date is None:
            raise ValueError("未找到可用日期，请先同步日历或手动指定日期。")
        return replace(request, time_input=replace(time_input, trade_date=trade_date))

    @staticmethod
    def _plan_snapshot(plan) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        units = list(plan.units or ())
        return {
            "plan_id": plan.plan_id,
            "dataset_key": plan.dataset_key,
            "run_profile": plan.run_profile,
            "unit_count": plan.planning.unit_count,
            "units_preview": [
                {
                    "unit_id": unit.unit_id,
                    "source_key": unit.source_key,
                    "trade_date": unit.trade_date.isoformat() if unit.trade_date else None,
                    "request_params": dict(unit.request_params or {}),
                    "operator_object": dict(unit.progress_context or {}),
                }
                for unit in units[:20]
            ],
            "units_preview_truncated": len(units) > 20,
        }

    @staticmethod
    def _plan_units_from_snapshot(plan) -> tuple[PlanUnit, ...]:  # type: ignore[no-untyped-def]
        return tuple(
            PlanUnit(
                unit_id=unit.unit_id,
                dataset_key=unit.dataset_key,
                source_key=unit.source_key,
                trade_date=unit.trade_date,
                request_params=dict(unit.request_params),
                progress_context=dict(unit.progress_context),
                pagination_policy=unit.pagination_policy,
                page_limit=unit.page_limit,
            )
            for unit in plan.units
        )

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
    def _create_node(
        session: Session,
        *,
        task_run_id: int,
        node_key: str,
        node_type: str,
        sequence_no: int,
        title: str,
        resource_key: str | None,
        time_input: dict[str, Any],
        context: dict[str, Any],
    ) -> TaskRunNode:
        node = TaskRunNode(
            task_run_id=task_run_id,
            node_key=node_key,
            node_type=node_type,
            sequence_no=sequence_no,
            title=title,
            resource_key=resource_key,
            status="running",
            time_input_json=time_input,
            context_json=context,
            started_at=datetime.now(timezone.utc),
        )
        session.add(node)
        session.flush()
        return node

    @staticmethod
    def _finish_node(
        node: TaskRunNode,
        *,
        status: str,
        rows_fetched: int = 0,
        rows_saved: int = 0,
        rows_rejected: int = 0,
    ) -> None:
        ended_at = datetime.now(timezone.utc)
        started_at = TaskRunDispatcher._as_aware_utc(node.started_at) if node.started_at else ended_at
        node.status = status
        node.rows_fetched = rows_fetched
        node.rows_saved = rows_saved
        node.rows_rejected = rows_rejected
        node.ended_at = ended_at
        node.duration_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)

    def _record_issue(
        self,
        session: Session,
        *,
        task_run: TaskRun,
        node_id: int | None,
        code: str,
        title: str,
        operator_message: str,
        suggested_action: str,
        technical_message: str,
        source_phase: str,
        severity: str,
    ) -> TaskRunIssue:
        now = datetime.now(timezone.utc)
        fingerprint = self._issue_fingerprint(task_run_id=task_run.id, node_id=node_id, code=code, technical_message=technical_message)
        existing = session.scalar(
            select(TaskRunIssue)
            .where(TaskRunIssue.task_run_id == task_run.id)
            .where(TaskRunIssue.fingerprint == fingerprint)
        )
        if existing is not None:
            task_run.primary_issue_id = existing.id
            return existing
        issue = TaskRunIssue(
            task_run_id=task_run.id,
            node_id=node_id,
            severity=severity,
            code=code,
            title=title,
            operator_message=truncate_text(operator_message, self.MAX_OPERATOR_MESSAGE_LENGTH),
            suggested_action=truncate_text(suggested_action, self.MAX_OPERATOR_MESSAGE_LENGTH),
            technical_message=truncate_text(technical_message, self.MAX_TECHNICAL_MESSAGE_LENGTH),
            technical_payload_json={
                "source_phase": source_phase,
                "node_id": node_id,
                "task_run_id": task_run.id,
            },
            object_json=self._current_object_snapshot(session, task_run.id),
            source_phase=source_phase,
            fingerprint=fingerprint,
            occurred_at=now,
        )
        session.add(issue)
        session.flush()
        task_run.primary_issue_id = issue.id
        return issue

    @staticmethod
    def _current_object_snapshot(session: Session, task_run_id: int) -> dict[str, Any]:
        value = session.scalar(select(TaskRun.current_object_json).where(TaskRun.id == task_run_id))
        return dict(value or {})

    @staticmethod
    def _issue_fingerprint(*, task_run_id: int, node_id: int | None, code: str, technical_message: str) -> str:
        digest = hashlib.sha256(str(technical_message or "").encode("utf-8")).hexdigest()[:24]
        return f"{task_run_id}:{node_id or 0}:{code}:{digest}"

    @staticmethod
    def _step_task_run(parent: TaskRun, spec_key: str, resource_key: str | None, params: dict[str, Any]) -> TaskRun:
        time_input = params.get("time_input") if isinstance(params.get("time_input"), dict) else dict(parent.time_input_json or {})
        filters = params.get("filters") if isinstance(params.get("filters"), dict) else dict(parent.filters_json or {})
        return TaskRun(
            id=parent.id,
            task_type="dataset_action",
            resource_key=resource_key or spec_key.rsplit(".", 1)[0],
            action=str(params.get("action") or parent.action or "maintain"),
            title=parent.title,
            trigger_source=parent.trigger_source,
            requested_by_user_id=parent.requested_by_user_id,
            schedule_id=parent.schedule_id,
            status=parent.status,
            requested_at=parent.requested_at,
            time_input_json=dict(time_input or {}),
            filters_json=dict(filters or {}),
            request_payload_json=dict(params or {}),
        )

    @staticmethod
    def _resource_key_from_spec_key(spec_key: str) -> str | None:
        if spec_key.endswith(".maintain"):
            return spec_key.rsplit(".", 1)[0]
        if "." in spec_key:
            return spec_key.split(".", 1)[1]
        return None

    @staticmethod
    def _resolve_maintenance_start_date(params: dict[str, Any]) -> date:
        value = params.get("start_date")
        if value is not None:
            return TaskRunDispatcher._parse_date(value)
        return date.fromisoformat(get_settings().history_start_date)

    @staticmethod
    def _resolve_maintenance_end_date(params: dict[str, Any]) -> date:
        value = params.get("end_date")
        if value is not None:
            return TaskRunDispatcher._parse_date(value)
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()

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
    def _optional_date(value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text_value = str(value).strip()
        return text_value or None

    @staticmethod
    def _parse_date(value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError(f"Invalid date value: {value!r}")

    @staticmethod
    def _as_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

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

    def _refresh_serving_light_if_needed(
        self,
        session: Session,
        *,
        task_run_id: int,
        resource: str,
        rows_saved: int,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_code: str | None = None,
    ) -> str | None:
        if resource != "daily":
            return None
        if rows_saved <= 0:
            return "轻量层刷新已跳过"
        effective_start_date = start_date or trade_date
        effective_end_date = end_date or trade_date
        if effective_start_date is None or effective_end_date is None:
            return None
        result = self.serving_light_refresh_service.refresh_equity_daily_bar(
            session,
            start_date=effective_start_date,
            end_date=effective_end_date,
            ts_code=ts_code,
            commit=True,
        )
        if result.touched_rows <= 0:
            return "轻量层刷新完成，未产生新增行"
        return f"轻量层刷新 {result.touched_rows} 行"
