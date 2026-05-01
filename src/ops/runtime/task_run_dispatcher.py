from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.config.settings import get_settings
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.ingestion.null_runtime import NullIngestionResultStore, NullRunRecorder
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshService
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from src.ops.action_catalog import MaintenanceActionDefinition, get_maintenance_action, get_workflow_definition
from src.utils import truncate_text


@dataclass(slots=True)
class TaskRunDispatchOutcome:
    status: str
    rows_fetched: int = 0
    rows_saved: int = 0
    rows_rejected: int = 0
    rejected_reason_counts: dict[str, int] | None = None
    summary_message: str | None = None
    issue_id: int | None = None
    status_reason_code: str | None = None


class TaskRunDispatcher:
    MAX_TECHNICAL_MESSAGE_LENGTH = 32_000
    MAX_OPERATOR_MESSAGE_LENGTH = 1_000
    SQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

    def __init__(self, serving_light_refresh_service: ServingLightRefreshService | None = None) -> None:
        self.serving_light_refresh_service = serving_light_refresh_service or ServingLightRefreshService()

    def dispatch(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        if task_run.task_type == "dataset_action":
            return self._dispatch_dataset_action(session, task_run)
        if task_run.task_type == "workflow":
            return self._dispatch_workflow(session, task_run)
        if task_run.task_type == "maintenance_action":
            return self._dispatch_maintenance_action(session, task_run)
        raise WebAppError(status_code=422, code="validation_error", message="不支持的任务类型")

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
            rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, summary_message = self._run_dataset_action_plan(
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
                rejected_reason_counts=rejected_reason_counts,
            )
            task_run.rejected_reason_counts_json = dict(rejected_reason_counts)
            task_run.unit_done = task_run.unit_total
            task_run.unit_failed = 0
            task_run.progress_percent = 100
            session.commit()
            return TaskRunDispatchOutcome(
                status="success",
                rows_fetched=rows_fetched,
                rows_saved=rows_saved,
                rows_rejected=rows_rejected,
                rejected_reason_counts=rejected_reason_counts,
                summary_message=summary_message,
            )
        except IngestionCanceledError as exc:
            session.rollback()
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=node.id,
                code="ingestion_canceled",
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
                code="ingestion_failed",
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
        target_key = str((task_run.request_payload_json or {}).get("target_key") or "")
        workflow = get_workflow_definition(target_key)
        if workflow is None:
            raise WebAppError(status_code=404, code="not_found", message="工作流不存在")

        total_fetched = 0
        total_saved = 0
        total_rejected = 0
        total_rejected_reason_counts: dict[str, int] = {}
        completed = 0
        failed = 0
        last_issue_id: int | None = None
        last_message: str | None = None
        for sequence_no, workflow_step in enumerate(workflow.steps, start=1):
            params = dict(task_run.request_payload_json or {})
            params.update(workflow_step.default_params)
            params.update(workflow_step.params_override)
            step_resource_key = workflow_step.dataset_key
            step_action_key = workflow_step.action_key
            if step_resource_key is None:
                try:
                    step_definition, step_action = get_dataset_definition_by_action_key(workflow_step.action_key)
                    step_resource_key = step_definition.dataset_key
                    step_action_key = step_definition.action_key(step_action)
                except KeyError:
                    step_resource_key = None
            node = self._create_node(
                session,
                task_run_id=task_run.id,
                node_key=workflow_step.step_key,
                node_type="workflow_step",
                sequence_no=sequence_no,
                title=workflow_step.display_name,
                resource_key=step_resource_key,
                time_input=dict(task_run.time_input_json or {}),
                context={"action_key": workflow_step.action_key},
            )
            task_run.current_node_id = node.id
            session.commit()
            try:
                if step_resource_key is not None:
                    step_run = self._step_task_run(task_run, step_action_key, step_resource_key, params)
                    request = self._prepare_dataset_action_request(session, self._build_dataset_action_request(step_run))
                    plan = DatasetActionResolver(session).build_plan(request)
                    rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, message = self._run_dataset_action_plan(
                        session,
                        step_run,
                        request,
                        plan,
                    )
                else:
                    action = get_maintenance_action(workflow_step.action_key)
                    if action is None:
                        raise ValueError(f"工作流步骤维护动作不存在：{workflow_step.action_key}")
                    rows_fetched, rows_saved, message = self._run_maintenance_action(session, action, params)
                    rows_rejected = max(rows_fetched - rows_saved, 0)
                    rejected_reason_counts = {}
                self._finish_node(
                    node,
                    status="success",
                    rows_fetched=rows_fetched,
                    rows_saved=rows_saved,
                    rows_rejected=rows_rejected,
                    rejected_reason_counts=rejected_reason_counts,
                )
                total_fetched += rows_fetched
                total_saved += rows_saved
                total_rejected += rows_rejected
                self._merge_reason_counts(total_rejected_reason_counts, rejected_reason_counts)
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
                if (workflow_step.failure_policy_override or workflow.failure_policy_default) != "continue_on_error":
                    break

        task_run.unit_total = len(workflow.steps)
        task_run.unit_done = completed
        task_run.unit_failed = failed
        task_run.progress_percent = int((completed + failed) / len(workflow.steps) * 100) if workflow.steps else 100
        status = "partial_success" if completed and failed else ("failed" if failed else "success")
        return TaskRunDispatchOutcome(
            status=status,
            rows_fetched=total_fetched,
            rows_saved=total_saved,
            rows_rejected=total_rejected,
            rejected_reason_counts=total_rejected_reason_counts,
            summary_message=last_message or workflow.display_name,
            issue_id=last_issue_id,
            status_reason_code="workflow_step_failed" if failed else None,
        )

    def _dispatch_maintenance_action(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        target_key = str((task_run.request_payload_json or {}).get("target_key") or "")
        action = get_maintenance_action(target_key)
        if action is None:
            raise WebAppError(status_code=404, code="not_found", message="系统维护动作不存在")
        node = self._create_node(
            session,
            task_run_id=task_run.id,
            node_key=target_key,
            node_type="maintenance_action",
            sequence_no=1,
            title=action.display_name,
            resource_key=task_run.resource_key,
            time_input=dict(task_run.time_input_json or {}),
            context={"action_key": target_key},
        )
        task_run.current_node_id = node.id
        session.commit()
        try:
            rows_fetched, rows_saved, message = self._run_maintenance_action(session, action, dict(task_run.request_payload_json or {}))
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
                code="maintenance_action_failed",
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
    ) -> tuple[int, int, int, dict[str, int], str | None]:  # type: ignore[no-untyped-def]
        service = DatasetMaintainService(
            session,
            dataset_key=plan.dataset_key,
            run_context=TaskRunIngestionContext(session),
            run_recorder=NullRunRecorder(),
            result_store=NullIngestionResultStore(),
        )
        filters = dict(action_request.filters or {})
        time_input = action_request.time_input
        parsed_trade_date: date | None = None
        if plan.run_profile == "point_incremental":
            parsed_trade_date = time_input.trade_date or self._resolve_default_trade_date(session)
            if parsed_trade_date is None:
                raise ValueError("未找到可用日期，请先同步日历或手动指定日期。")
            if not time_input.month and self._is_closed_trade_date(session, parsed_trade_date):
                definition = get_dataset_definition(plan.dataset_key)
                return 0, 0, 0, {}, f"{definition.display_name}：{parsed_trade_date.isoformat()} 非交易日，已跳过维护。"
            action_request = DatasetActionRequest(
                dataset_key=action_request.dataset_key,
                action=action_request.action,
                time_input=replace(action_request.time_input, trade_date=parsed_trade_date),
                filters=filters,
                trigger_source=action_request.trigger_source,
                requested_by_user_id=action_request.requested_by_user_id,
                schedule_id=action_request.schedule_id,
                workflow_key=action_request.workflow_key,
                run_id=task_run.id,
            )
        result = service.maintain(
            default_time_mode=None,
            run_id=task_run.id,
            _plan=plan,
            _action_request=action_request,
        )

        rows_fetched = int(result.rows_fetched or 0)
        rows_saved = int(result.rows_written or 0)
        rows_rejected = int(result.rows_rejected or 0)
        rejected_reason_counts = self._normalize_reason_counts(result.rejected_reason_counts)
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
        return rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, summary_message

    def _build_dataset_action_request(self, task_run: TaskRun) -> DatasetActionRequest:
        time_payload = dict(task_run.time_input_json or {})
        filters = dict(task_run.filters_json or {})
        resource_key = str(task_run.resource_key or "").strip()
        if not resource_key:
            raise ValueError("任务缺少维护对象")
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
            run_id=task_run.id,
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

    def _run_maintenance_action(
        self,
        session: Session,
        action: MaintenanceActionDefinition,
        params: dict[str, Any],
    ) -> tuple[int, int, str | None]:
        if action.executor_key == "refresh_materialized_view":
            view_name = self._required_execution_text(action.execution_config, "view_name")
            session.execute(text(f"REFRESH MATERIALIZED VIEW {self._sql_identifier(view_name)}"))
            session.commit()
            return 0, 0, "物化视图已刷新"
        if action.executor_key == "rebuild_index_period_serving":
            start_date = self._resolve_maintenance_start_date(params)
            end_date = self._resolve_maintenance_end_date(params)
            if start_date > end_date:
                raise ValueError("开始日期不能晚于结束日期")
            calendar_table = self._required_execution_text(action.execution_config, "calendar_table")
            source_table = self._required_execution_text(action.execution_config, "source_table")
            index_table = self._required_execution_text(action.execution_config, "index_table")
            period_targets = self._required_period_targets(action.execution_config)
            rows_by_granularity: dict[str, int] = {}
            for period_target in period_targets:
                target_table = self._required_execution_text(period_target, "target_table")
                period_granularity = self._required_execution_text(period_target, "period_granularity")
                rows_by_granularity[period_granularity] = self._rebuild_index_period_serving(
                    session=session,
                    target_table=target_table,
                    source_table=source_table,
                    index_table=index_table,
                    calendar_table=calendar_table,
                    start_date=start_date,
                    end_date=end_date,
                    period_granularity=period_granularity,
                )
            session.commit()
            written = sum(rows_by_granularity.values())
            detail = " ".join(f"{granularity}={rows}" for granularity, rows in rows_by_granularity.items())
            return 0, written, f"指数周期服务层已重建 {detail}".strip()
        raise ValueError(f"不支持的系统维护执行器：{action.executor_key}")

    def _rebuild_index_period_serving(
        self,
        *,
        session: Session,
        target_table: str,
        source_table: str,
        index_table: str,
        calendar_table: str,
        start_date: date,
        end_date: date,
        period_granularity: str,
    ) -> int:
        target_table_sql = self._sql_identifier(target_table)
        source_table_sql = self._sql_identifier(source_table)
        index_table_sql = self._sql_identifier(index_table)
        calendar_table_sql = self._sql_identifier(calendar_table)
        if period_granularity == "week":
            calendar_period_expr = "date_trunc('week', trade_date)::date"
            daily_period_expr = "date_trunc('week', d.trade_date)::date"
        elif period_granularity == "month":
            calendar_period_expr = "date_trunc('month', trade_date)::date"
            daily_period_expr = "date_trunc('month', d.trade_date)::date"
        else:
            raise ValueError(f"不支持的周期粒度：{period_granularity}")
        session.execute(
            text(
                f"""
                delete from {target_table_sql}
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
                from {calendar_table_sql}
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
                from {source_table_sql} d
                join {index_table_sql} b on b.ts_code = d.ts_code
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
            insert into {target_table_sql} (
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
            left join {target_table_sql} existing_trade
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
            where {target_table_sql}.source <> 'api'
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

    @classmethod
    def _sql_identifier(cls, value: str) -> str:
        if not cls.SQL_IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"SQL 标识符无效：{value!r}")
        return value

    @staticmethod
    def _required_execution_text(config: Mapping[str, Any], key: str) -> str:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"系统维护动作执行配置缺少 {key}")
        return value.strip()

    @staticmethod
    def _required_period_targets(config: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        value = config.get("period_targets")
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError("系统维护动作执行配置缺少周期目标")
        targets = tuple(target for target in value if isinstance(target, Mapping))
        if len(targets) != len(value) or not targets:
            raise ValueError("系统维护动作执行配置中的周期目标无效")
        return targets

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
        rows_fetched: int | None = None,
        rows_saved: int | None = None,
        rows_rejected: int | None = None,
        rejected_reason_counts: dict[str, int] | None = None,
    ) -> None:
        ended_at = datetime.now(timezone.utc)
        started_at = TaskRunDispatcher._as_aware_utc(node.started_at) if node.started_at else ended_at
        node.status = status
        if rows_fetched is not None:
            node.rows_fetched = rows_fetched
        if rows_saved is not None:
            node.rows_saved = rows_saved
        if rows_rejected is not None:
            node.rows_rejected = rows_rejected
        if rejected_reason_counts is not None:
            node.rejected_reason_counts_json = TaskRunDispatcher._normalize_reason_counts(rejected_reason_counts)
        node.ended_at = ended_at
        node.duration_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)

    @staticmethod
    def _normalize_reason_counts(reason_counts: dict[str, int] | None) -> dict[str, int]:
        if not isinstance(reason_counts, dict):
            return {}
        normalized: dict[str, int] = {}
        for raw_key, raw_count in reason_counts.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            normalized[key] = normalized.get(key, 0) + count
        return normalized

    @staticmethod
    def _merge_reason_counts(target: dict[str, int], source: dict[str, int] | None) -> None:
        for key, count in TaskRunDispatcher._normalize_reason_counts(source).items():
            target[key] = target.get(key, 0) + count

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
    def _step_task_run(parent: TaskRun, action_key: str, resource_key: str | None, params: dict[str, Any]) -> TaskRun:
        time_input = params.get("time_input") if isinstance(params.get("time_input"), dict) else dict(parent.time_input_json or {})
        filters = params.get("filters") if isinstance(params.get("filters"), dict) else dict(parent.filters_json or {})
        return TaskRun(
            id=parent.id,
            task_type="dataset_action",
            resource_key=resource_key,
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
        raise ValueError(f"日期值无效：{value!r}")

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
