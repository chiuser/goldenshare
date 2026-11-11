from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.app.exceptions import WebAppError
from src.foundation.ingestion.execution_scope import execution_observation_timeout
from src.foundation.config.settings import get_settings
from src.foundation.datasets.registry import get_dataset_definition, get_dataset_definition_by_action_key
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.index_period_raw import MISSING_PERIOD_CODE
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.service import DatasetMaintainService
from src.foundation.ingestion.null_runtime import NullIngestionResultStore, NullRunRecorder
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.dataset_action_request_adapter import dataset_action_trigger_source
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.contracts.external_task import ExternalTaskExecutor
from src.ops.runtime.index_period_serving_executor import IndexPeriodServingExecutor
from src.ops.runtime.maintenance_executor import (
    MaintenanceInputAuditBlockedError,
    MaintenanceExecutionPlan,
    MaintenanceExecutionRequest,
    MaintenanceExecutionUnit,
    MaintenanceExecutor,
    MaintenanceTaskRunContext,
    TaskRunAwareMaintenanceInputAuditor,
    TaskRunAwareMaintenanceExecutor,
    TaskRunAwareMaintenancePlanner,
)
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshService
from src.ops.services.ingestion_error_presentation import present_ingestion_error, structured_error_payload
from src.ops.services.index_period_schedule import scheduled_index_raw_serving_action
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from src.ops.services.task_run_maintenance_plan_context import TaskRunMaintenancePlanContext
from src.ops.action_catalog import MaintenanceActionDefinition, get_maintenance_action, get_workflow_definition
from src.utils import truncate_text


@dataclass(slots=True)
class TaskRunDispatchOutcome:
    status: str
    rows_fetched: int = 0
    rows_saved: int = 0
    rows_rejected: int = 0
    rows_deduplicated: int = 0
    ingestion_diagnostics: dict[str, Any] | None = None
    rejected_reason_counts: dict[str, int] | None = None
    rejected_reason_samples: dict[str, list[dict[str, Any]]] | None = None
    summary_message: str | None = None
    issue_id: int | None = None
    status_reason_code: str | None = None


class TaskRunDispatcher:
    MAX_TECHNICAL_MESSAGE_LENGTH = 32_000
    MAX_OPERATOR_MESSAGE_LENGTH = 1_000
    SQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

    def __init__(
        self,
        serving_light_refresh_service: ServingLightRefreshService | None = None,
        *,
        maintenance_executors: Mapping[str, MaintenanceExecutor | IndexPeriodServingExecutor] | None = None,
        external_executors: Mapping[str, ExternalTaskExecutor] | None = None,
    ) -> None:
        self.serving_light_refresh_service = serving_light_refresh_service or ServingLightRefreshService()
        self.maintenance_executors = dict(maintenance_executors or {})
        self.external_executors = dict(external_executors or {})

    def dispatch(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        external = self.external_executors.get(task_run.task_type)
        if external is not None:
            outcome = external.execute(
                task_run_id=task_run.id,
                request_payload=dict(task_run.request_payload_json or {}),
            )
            return TaskRunDispatchOutcome(
                status=outcome.status,
                rows_fetched=outcome.rows_fetched,
                rows_saved=outcome.rows_saved,
                rows_rejected=outcome.rows_rejected,
                summary_message=outcome.summary_message,
                status_reason_code=outcome.status_reason_code,
            )
        if task_run.task_type == "dataset_action":
            return self._dispatch_dataset_action(session, task_run)
        if task_run.task_type == "workflow":
            return self._dispatch_workflow(session, task_run)
        if task_run.task_type == "maintenance_action":
            return self._dispatch_maintenance_action(session, task_run)
        raise WebAppError(status_code=422, code="validation_error", message="不支持的任务类型")

    def _dispatch_dataset_action(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        try:
            action_request = self._prepare_dataset_action_request(session, self._build_dataset_action_request(task_run))
            plan = DatasetActionResolver(session).build_plan(action_request)
        except IngestionError as exc:
            session.rollback()
            presentation = present_ingestion_error(exc.structured_error)
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=None,
                code=exc.structured_error.error_code,
                title=presentation.title,
                operator_message=presentation.operator_message,
                suggested_action=presentation.suggested_action,
                technical_message=str(exc),
                source_phase=exc.structured_error.phase,
                severity="error",
                technical_payload={"structured_error": structured_error_payload(exc.structured_error)},
            )
            session.commit()
            return TaskRunDispatchOutcome(
                status="failed",
                summary_message=issue.operator_message,
                issue_id=issue.id,
                status_reason_code=issue.code,
            )
        node = self._create_node(
            session,
            task_run_id=task_run.id,
            node_key=plan.plan_id,
            node_type="dataset_plan",
            sequence_no=1,
            title=f"维护 {task_run.title}",
            resource_key=plan.dataset_key,
            time_input=self._dataset_time_input_payload(action_request.time_input),
            context={"run_profile": plan.run_profile},
        )
        task_run.current_node_id = node.id
        task_run.unit_total = int(plan.planning.unit_count or len(plan.units))
        task_run.plan_snapshot_json = self._plan_snapshot(plan)
        if get_dataset_definition(plan.dataset_key).planning.index_period_raw_policy is not None:
            task_run.ingestion_diagnostics_json = {"index_period_raw": {}}
        session.commit()
        try:
            (
                rows_fetched,
                rows_saved,
                rows_rejected,
                rejected_reason_counts,
                rejected_reason_samples,
                summary_message,
            ) = self._run_dataset_action_plan(
                session,
                task_run,
                action_request,
                plan,
            )
            status, issue = self._index_period_raw_result(session, task_run, node, task_run)
            if not (status == "success" and rows_saved > 0 and scheduled_index_raw_serving_action(task_run)):
                self._finish_node(
                    node,
                    status=status,
                    rows_fetched=rows_fetched,
                    rows_saved=rows_saved,
                    rows_rejected=rows_rejected,
                    rejected_reason_counts=rejected_reason_counts,
                    rejected_reason_samples=rejected_reason_samples,
                )
            task_run.rejected_reason_counts_json = dict(rejected_reason_counts)
            task_run.rejected_reason_samples_json = dict(rejected_reason_samples)
            if "index_period_raw" in (task_run.ingestion_diagnostics_json or {}):
                task_run.rows_fetched = rows_fetched
                task_run.rows_saved = rows_saved
                task_run.rows_rejected = rows_rejected
            if issue is None:
                task_run.unit_done = task_run.unit_total
                task_run.unit_failed = 0
            task_run.progress_percent = 100
            session.commit()
            return TaskRunDispatchOutcome(
                status=status,
                issue_id=issue.id if issue else None,
                status_reason_code=issue.code if issue else None,
                rows_fetched=rows_fetched,
                rows_saved=rows_saved,
                rows_rejected=rows_rejected,
                rejected_reason_counts=rejected_reason_counts,
                rejected_reason_samples=rejected_reason_samples,
                summary_message=summary_message,
            )
        except IngestionCanceledError as exc:
            session.rollback()
            self._restore_index_period_raw_progress(task_run, exc)
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
            self._restore_index_period_raw_progress(task_run, exc)
            period_message = self._index_period_raw_error_message(exc)
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=node.id,
                code=exc.structured_error.error_code if period_message else "ingestion_failed",
                title="任务处理失败",
                operator_message=period_message or "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
                suggested_action=("查看失败阶段后，按原范围重试。" if period_message else
                                  "先确认已保存数据和失败位置，再决定是否缩小范围重新提交。"),
                technical_message=str(exc),
                source_phase="execute",
                severity="error",
                technical_payload=self._technical_payload_for_exception(exc),
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
        total_rejected_reason_samples: dict[str, list[dict[str, Any]]] = {}
        completed = 0
        failed = 0
        had_partial_step = False
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
                step_status, step_issue = "success", None
                if step_resource_key is not None:
                    step_run = self._step_task_run(task_run, step_action_key, step_resource_key, params)
                    request = self._prepare_dataset_action_request(session, self._build_dataset_action_request(step_run))
                    node.time_input_json = self._dataset_time_input_payload(request.time_input)
                    plan = DatasetActionResolver(session).build_plan(request)
                    (
                        rows_fetched,
                        rows_saved,
                        rows_rejected,
                        rejected_reason_counts,
                        rejected_reason_samples,
                        message,
                    ) = self._run_dataset_action_plan(
                        session,
                        step_run,
                        request,
                        plan,
                    )
                    step_status, step_issue = self._index_period_raw_result(session, task_run, node, step_run)
                else:
                    action = get_maintenance_action(workflow_step.action_key)
                    if action is None:
                        raise ValueError(f"工作流步骤维护动作不存在：{workflow_step.action_key}")
                    rows_fetched, rows_saved, message = self._run_maintenance_action(session, action, params)
                    rows_rejected = max(rows_fetched - rows_saved, 0)
                    rejected_reason_counts = {}
                    rejected_reason_samples = {}
                self._finish_node(
                    node,
                    status=step_status,
                    rows_fetched=rows_fetched,
                    rows_saved=rows_saved,
                    rows_rejected=rows_rejected,
                    rejected_reason_counts=rejected_reason_counts,
                    rejected_reason_samples=rejected_reason_samples,
                )
                total_fetched += rows_fetched
                total_saved += rows_saved
                total_rejected += rows_rejected
                self._merge_reason_counts(total_rejected_reason_counts, rejected_reason_counts)
                self._merge_reason_samples(total_rejected_reason_samples, rejected_reason_samples)
                if step_issue is None:
                    completed += 1
                else:
                    failed += 1
                    had_partial_step |= step_status == "partial_success"
                    last_issue_id = step_issue.id
                last_message = message
                session.commit()
                if step_issue is not None and (workflow_step.failure_policy_override or workflow.failure_policy_default) != "continue_on_error":
                    break
            except Exception as exc:
                session.rollback()
                progress = getattr(exc, "index_period_raw_progress", None)
                if progress:
                    total_fetched += progress["rows_fetched"]
                    total_saved += progress["rows_saved"]
                    total_rejected += progress["rows_rejected"]
                was_canceled = isinstance(exc, IngestionCanceledError) and progress is not None
                failed += 0 if was_canceled else 1
                issue = self._record_issue(
                    session,
                    task_run=task_run,
                    node_id=node.id,
                    code="ingestion_canceled" if was_canceled else "workflow_step_failed",
                    title="工作流步骤失败",
                    operator_message=(str(exc) if was_canceled else self._index_period_raw_error_message(exc))
                    or f"{workflow_step.display_name} 处理失败。",
                    suggested_action="查看技术诊断，确认失败步骤后再决定是否重新提交。",
                    technical_message=str(exc),
                    source_phase="execute",
                    severity="error",
                    technical_payload=self._technical_payload_for_exception(exc),
                )
                node = session.get(TaskRunNode, node.id)
                if node is not None:
                    node.issue_id = issue.id
                    self._finish_node(
                        node, status="canceled" if was_canceled else "failed",
                        rows_fetched=progress["rows_fetched"] if progress else None,
                        rows_saved=progress["rows_saved"] if progress else None,
                        rows_rejected=progress["rows_rejected"] if progress else None,
                        ingestion_diagnostics=progress["ingestion_diagnostics"] if progress else None,
                    )
                session.commit()
                if was_canceled:
                    return TaskRunDispatchOutcome(
                        status="canceled", rows_fetched=total_fetched, rows_saved=total_saved,
                        rows_rejected=total_rejected, summary_message=issue.operator_message, issue_id=issue.id,
                    )
                last_issue_id = issue.id
                last_message = issue.operator_message
                if (workflow_step.failure_policy_override or workflow.failure_policy_default) != "continue_on_error":
                    break

        task_run.unit_total = len(workflow.steps)
        task_run.unit_done = completed
        task_run.unit_failed = failed
        task_run.progress_percent = int((completed + failed) / len(workflow.steps) * 100) if workflow.steps else 100
        status = "partial_success" if (completed or had_partial_step) and failed else ("failed" if failed else "success")
        return TaskRunDispatchOutcome(
            status=status,
            rows_fetched=total_fetched,
            rows_saved=total_saved,
            rows_rejected=total_rejected,
            rejected_reason_counts=total_rejected_reason_counts,
            rejected_reason_samples=total_rejected_reason_samples,
            summary_message=last_message or workflow.display_name,
            issue_id=last_issue_id,
            status_reason_code="workflow_step_failed" if failed else None,
        )

    def _dispatch_maintenance_action(self, session: Session, task_run: TaskRun) -> TaskRunDispatchOutcome:
        target_key = str((task_run.request_payload_json or {}).get("target_key") or "")
        action = get_maintenance_action(target_key)
        if action is None:
            raise WebAppError(status_code=404, code="not_found", message="系统维护动作不存在")
        executor = self.maintenance_executors.get(action.executor_key)
        if isinstance(executor, IndexPeriodServingExecutor):
            return self._dispatch_index_period_serving(session, task_run, action, executor)
        if executor is not None:
            return self._dispatch_registered_maintenance_action(
                session=session,
                task_run=task_run,
                action=action,
                executor=executor,
            )
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

    def _dispatch_index_period_serving(
        self, session: Session, task_run: TaskRun, action: MaintenanceActionDefinition,
        executor: IndexPeriodServingExecutor,
    ) -> TaskRunDispatchOutcome:
        params = self._maintenance_params(task_run)
        frequency = action.execution_config["frequency"]
        scope = {"frequency": frequency, "trade_date": params.get("trade_date")}
        diagnostics = {"index_period_serving": scope}
        run_id = task_run.id
        node = self._create_node(
            session, task_run_id=run_id, node_key=action.key, node_type="maintenance_action",
            sequence_no=1, title=action.display_name, resource_key=task_run.resource_key,
            time_input=dict(task_run.time_input_json or {}), context={"action_key": action.key},
        )
        task_run.current_node_id = node.id
        task_run.ingestion_diagnostics_json = diagnostics
        session.commit()

        observer = TaskRunIngestionContext(session)
        failures: list[dict[str, Any]] = []
        total = done = fetched = saved = 0
        status, issue_code, message = "success", None, action.display_name
        active_code = None
        try:
            self._raise_if_task_cancel_requested(session, run_id)
            scheduled_target = (
                date.fromisoformat(task_run.time_input_json["trade_date"]) if task_run.schedule_id is not None else None
            )
            if scheduled_target is not None:
                executor.check_schedule_cutoff(frequency, scheduled_target)
            period, codes, list_dates = executor.prepare(frequency, params)
            total = len(codes)
            for code in codes:
                active_code = code
                self._raise_if_task_cancel_requested(session, run_id)
                observer.update_progress(
                    run_id=run_id, unit_done=done, unit_failed=len(failures), total=total,
                    message=action.display_name, rows_fetched=fetched, rows_saved=saved,
                    ingestion_diagnostics=diagnostics,
                    current_object={
                        "entity": {"kind": "index", "code": code},
                        "time": {"field": "trade_date", "point": period.trade_date.isoformat()},
                        "attributes": {"freq": "周线" if frequency == "week" else "月线"},
                    },
                )
                if scheduled_target is not None:
                    executor.check_schedule_cutoff(frequency, scheduled_target)
                result = executor.execute_code(period, code, list_dates.get(code))
                fetched += result.rows_fetched
                saved += result.rows_saved
                if result.failure is None:
                    done += 1
                else:
                    failures.append({"message": result.failure.message, **structured_error_payload(result.failure)})
            self._raise_if_task_cancel_requested(session, run_id)
            if failures:
                status, issue_code = "failed", "index_period_serving.code_failures"
                message = f"{action.display_name}失败，{len(failures)} 个指数未更新，实际保存 {saved} 行。"
        except IngestionCanceledError:
            status, issue_code = "canceled", "ingestion_canceled"
            message = "任务已在指数处理边界停止。"
        except IngestionError as exc:
            status, issue_code, message = "failed", exc.structured_error.error_code, str(exc)
            failures.append({"message": message, **structured_error_payload(exc.structured_error)})
        except SQLAlchemyError as exc:
            status, issue_code = "failed", "maintenance_executor_failed"
            message = f"{action.display_name}数据库执行失败。"
            failures.append({"ts_code": active_code, "phase": "execute", "exception": type(exc).__name__})

        session.rollback()
        task_run.unit_total = total
        task_run.unit_done = done
        task_run.unit_failed = len(failures)
        task_run.progress_percent = (done + len(failures)) * 100 // total if total else 0
        issue = None
        if issue_code is not None:
            issue = self._record_issue(
                session, task_run=task_run, node_id=node.id, code=issue_code, title=action.display_name,
                operator_message=message,
                suggested_action=(
                    "在手动更新入口指定原目标日补数。"
                    if issue_code == "index_period_serving.schedule_expired"
                    else "查看技术诊断，确认原目标日和代码后重试。"
                ),
                technical_message=message, source_phase="execute",
                severity="warning" if status == "canceled" else "error",
                technical_payload={**scope, "rows_saved": saved, "failures": failures},
            )
            node.issue_id = issue.id
        self._finish_node(node, status=status, rows_fetched=fetched, rows_saved=saved, ingestion_diagnostics=diagnostics)
        session.commit()
        return TaskRunDispatchOutcome(
            status=status, rows_fetched=fetched, rows_saved=saved, summary_message=message,
            ingestion_diagnostics=diagnostics, issue_id=issue.id if issue else None, status_reason_code=issue_code,
        )

    def _dispatch_registered_maintenance_action(
        self,
        *,
        session: Session,
        task_run: TaskRun,
        action: MaintenanceActionDefinition,
        executor: MaintenanceExecutor,
    ) -> TaskRunDispatchOutcome:
        params = self._maintenance_params(task_run)
        current_node_id: int | None = None
        unit_sequence_offset = 0
        try:
            if action.execution_config.get("execution_style") == "audit_then_apply":
                self._validate_audit_then_apply_params(params)
                if not isinstance(executor, TaskRunAwareMaintenanceInputAuditor):
                    raise RuntimeError(
                        "audit_then_apply maintenance action requires a task-aware input auditor"
                    )
                node = self._create_node(
                    session,
                    task_run_id=task_run.id,
                    node_key=f"{action.key}:input-audit",
                    node_type="maintenance_plan",
                    sequence_no=1,
                    title=f"{action.display_name}：输入审计",
                    resource_key=task_run.resource_key,
                    time_input=dict(task_run.time_input_json or {}),
                    context={
                        "action_key": action.key,
                        "execution_style": "audit_then_apply",
                    },
                )
                current_node_id = node.id
                task_run.current_node_id = node.id
                task_run.unit_total = 0
                task_run.unit_done = 0
                task_run.unit_failed = 0
                task_run.progress_percent = None
                session.commit()
                plan = executor.audit_for_task_run(
                    MaintenanceExecutionRequest(action_key=action.key, params=params),
                    context=TaskRunMaintenancePlanContext(
                        session,
                        task_run_id=task_run.id,
                        action_key=action.key,
                        executor_key=action.executor_key,
                    ),
                )
                session.expire_all()
                task_run = session.get(TaskRun, task_run.id)
                node = session.get(TaskRunNode, current_node_id)
                if task_run is None or node is None:
                    raise RuntimeError("maintenance input audit task or node disappeared")
                task_run.plan_snapshot_json = self._maintenance_input_audit_snapshot(
                    action=action,
                    plan=plan,
                )
                if not plan.apply_ready:
                    session.commit()
                    audit_issues = plan.metadata.get("audit_issues")
                    blocking_code = "maintenance_input_audit_blocked"
                    if isinstance(audit_issues, Sequence):
                        for audit_issue in audit_issues:
                            if (
                                isinstance(audit_issue, Mapping)
                                and audit_issue.get("blocking") is True
                                and str(audit_issue.get("code") or "").strip()
                            ):
                                blocking_code = str(audit_issue["code"])
                                break
                    raise MaintenanceInputAuditBlockedError(
                        "maintenance input audit is blocked",
                        code=blocking_code,
                    )
                self._finish_node(
                    node,
                    status="success",
                    ingestion_diagnostics={
                        "maintenance_audit": {
                            "phase": "AUDIT_PASSED",
                            "audit_hash": plan.plan_hash,
                        }
                    },
                )
                units = plan.units
                unit_sequence_offset = 1
                session.commit()
            elif action.execution_config.get("plan_apply_replay") is True and str(
                params.get("execution_mode") or ""
            ).upper() == "PLAN":
                self._validate_replay_plan_params(params)
                node = self._create_node(
                    session,
                    task_run_id=task_run.id,
                    node_key=f"{action.key}:plan",
                    node_type="maintenance_plan",
                    sequence_no=1,
                    title=f"{action.display_name}：生成计划",
                    resource_key=task_run.resource_key,
                    time_input=dict(task_run.time_input_json or {}),
                    context={"action_key": action.key, "execution_mode": "PLAN"},
                )
                current_node_id = node.id
                task_run.current_node_id = node.id
                task_aware_plan = isinstance(executor, TaskRunAwareMaintenancePlanner)
                task_run.unit_total = 0 if task_aware_plan else 1
                task_run.unit_done = 0
                task_run.unit_failed = 0
                task_run.progress_percent = None if task_aware_plan else 0
                session.commit()
                request = MaintenanceExecutionRequest(action_key=action.key, params=params)
                if task_aware_plan:
                    plan = executor.plan_for_task_run(
                        request,
                        context=TaskRunMaintenancePlanContext(
                            session,
                            task_run_id=task_run.id,
                            action_key=action.key,
                            executor_key=action.executor_key,
                        ),
                    )
                else:
                    plan = executor.plan(request)
                session.expire_all()
                task_run = session.get(TaskRun, task_run.id)
                node = session.get(TaskRunNode, current_node_id)
                if task_run is None or node is None:
                    raise RuntimeError("maintenance PLAN task or node disappeared")
                task_run.plan_snapshot_json = self._maintenance_plan_snapshot(
                    action=action,
                    plan=plan,
                    snapshot_state="FROZEN" if task_aware_plan else None,
                )
                plan_total = self._maintenance_plan_total(plan) if task_aware_plan else 1
                task_run.unit_total = plan_total
                task_run.unit_done = plan_total
                task_run.unit_failed = 0
                task_run.progress_percent = 100
                self._finish_node(node, status="success")
                session.commit()
                gap_count = len(plan.metadata.get("gaps") or ()) if isinstance(plan.metadata, Mapping) else 0
                return TaskRunDispatchOutcome(
                    status="success",
                    summary_message=(
                        f"{action.display_name}计划已冻结：units={len(plan.units)} gaps={gap_count} "
                        f"apply_ready={str(plan.apply_ready).lower()} plan_hash={plan.plan_hash}"
                    ),
                )

            elif action.execution_config.get("plan_apply_replay") is True:
                self._validate_replay_apply_params(params)
                units = self._load_replay_apply_units(session=session, task_run=task_run, action=action, params=params)
            elif action.execution_config.get("execution_style") != "audit_then_apply":
                plan = executor.plan(MaintenanceExecutionRequest(action_key=action.key, params=params))
                task_run.plan_snapshot_json = self._maintenance_plan_snapshot(action=action, plan=plan)
                if not plan.apply_ready:
                    raise ValueError("maintenance plan is not apply-ready")
                units = plan.units

            task_run.unit_total = len(units)
            task_run.unit_done = 0
            task_run.unit_failed = 0
            task_run.progress_percent = 0
            session.commit()
            total_fetched = 0
            total_saved = 0
            total_rejected = 0
            total_deduplicated = 0
            rejected_reason_counts: dict[str, int] = {}
            ingestion_diagnostics: dict[str, Any] = {}
            last_message: str | None = None
            for sequence_no, unit in enumerate(units, start=1):
                if action.execution_config.get("execution_style") == "audit_then_apply":
                    self._raise_if_task_cancel_requested(session, task_run.id)
                node = self._create_node(
                    session,
                    task_run_id=task_run.id,
                    node_key=unit.unit_key,
                    node_type="maintenance_unit",
                    sequence_no=sequence_no + unit_sequence_offset,
                    title=f"{action.display_name}：{unit.unit_key}",
                    resource_key=task_run.resource_key,
                    time_input=self._unit_time_input(unit),
                    context={"action_key": action.key, "executor_key": action.executor_key},
                )
                current_node_id = node.id
                task_run.current_node_id = node.id
                task_run.current_object_json = dict(unit.payload)
                session.commit()

                if isinstance(executor, TaskRunAwareMaintenanceExecutor):
                    result = executor.execute_unit_for_task_run(
                        unit,
                        context=MaintenanceTaskRunContext(
                            task_run_id=task_run.id,
                            run_context=TaskRunIngestionContext(session),
                        ),
                    )
                else:
                    result = executor.execute_unit(unit)
                self._finish_node(
                    node,
                    status="success",
                    rows_fetched=result.rows_fetched,
                    rows_saved=result.rows_saved,
                    rows_rejected=result.rows_rejected,
                    rows_deduplicated=int(result.metadata.get("rows_deduplicated") or 0),
                    ingestion_diagnostics=dict(result.metadata),
                    rejected_reason_counts=dict(result.rejected_reason_counts),
                    rejected_reason_samples={},
                )
                total_fetched += result.rows_fetched
                total_saved += result.rows_saved
                total_rejected += result.rows_rejected
                total_deduplicated += int(result.metadata.get("rows_deduplicated") or 0)
                self._merge_reason_counts(rejected_reason_counts, dict(result.rejected_reason_counts))
                self._merge_diagnostics(ingestion_diagnostics, result.metadata)
                last_message = result.summary_message
                task_run.unit_done = sequence_no
                task_run.progress_percent = int(sequence_no / len(units) * 100) if units else 100
                session.commit()
            return TaskRunDispatchOutcome(
                status="success",
                rows_fetched=total_fetched,
                rows_saved=total_saved,
                rows_rejected=total_rejected,
                rows_deduplicated=total_deduplicated,
                ingestion_diagnostics=ingestion_diagnostics,
                rejected_reason_counts=rejected_reason_counts,
                summary_message=last_message or action.display_name,
            )
        except IngestionCanceledError:
            session.rollback()
            if current_node_id is not None:
                node = session.get(TaskRunNode, current_node_id)
                if node is not None and node.status in {"pending", "running"}:
                    self._finish_node(node, status="canceled")
            current_task_run = session.get(TaskRun, task_run.id)
            if current_task_run is not None:
                current_task_run.status_reason_code = "ingestion_canceled"
            session.commit()
            return TaskRunDispatchOutcome(
                status="canceled",
                summary_message="任务已收到停止请求，并在当前计划边界结束。",
                status_reason_code="ingestion_canceled",
            )
        except Exception as exc:
            session.rollback()
            error_code = str(getattr(exc, "code", "") or "maintenance_executor_failed")
            if action.execution_config.get("execution_style") == "audit_then_apply":
                suggested_action = (
                    "查看输入审计问题；由上游修复来源后，重新提交同一日期范围。"
                )
            else:
                suggested_action = (
                    "查看技术诊断和已完成单元；历史回放应从原计划续跑，不要重新规划。"
                )
            issue = self._record_issue(
                session,
                task_run=task_run,
                node_id=current_node_id,
                code=error_code,
                title="系统维护执行失败",
                operator_message="系统维护动作执行失败。",
                suggested_action=suggested_action,
                technical_message=str(exc),
                source_phase="execute",
                severity="error",
            )
            if current_node_id is not None:
                node = session.get(TaskRunNode, current_node_id)
                if node is not None:
                    node.issue_id = issue.id
                    self._finish_node(node, status="failed")
            task_run.unit_failed = 1
            session.commit()
            return TaskRunDispatchOutcome(
                status="failed",
                summary_message=issue.operator_message,
                issue_id=issue.id,
                status_reason_code=issue.code,
            )

    @staticmethod
    def _maintenance_params(task_run: TaskRun) -> dict[str, Any]:
        request_payload = dict(task_run.request_payload_json or {})
        params = {
            key: value
            for key, value in request_payload.items()
            if key not in {"task_type", "resource_key", "action", "target_type", "target_key", "time_input", "filters"}
        }
        time_input = request_payload.get("time_input")
        if isinstance(time_input, Mapping):
            params.update({key: value for key, value in time_input.items() if key != "mode" and value not in (None, "")})
        params.update(dict(task_run.time_input_json or {}))
        params.pop("mode", None)
        filters = request_payload.get("filters")
        if isinstance(filters, Mapping):
            params.update({key: value for key, value in filters.items() if value not in (None, "")})
        params.update(dict(task_run.filters_json or {}))
        return params

    @staticmethod
    def _validate_replay_plan_params(params: Mapping[str, Any]) -> None:
        if not params.get("start_date") or not params.get("end_date"):
            raise ValueError("replay PLAN requires start_date and end_date")
        if params.get("plan_task_run_id") not in (None, "") or params.get("plan_hash") not in (None, ""):
            raise ValueError("replay PLAN forbids plan_task_run_id and plan_hash")

    @staticmethod
    def _validate_audit_then_apply_params(params: Mapping[str, Any]) -> None:
        if not params.get("start_date") or not params.get("end_date"):
            raise ValueError("audit_then_apply requires start_date and end_date")
        forbidden = {
            key
            for key in ("execution_mode", "plan_task_run_id", "plan_hash")
            if params.get(key) not in (None, "")
        }
        if forbidden:
            raise ValueError(
                "audit_then_apply forbids legacy PLAN/APPLY parameters"
            )

    @staticmethod
    def _validate_replay_apply_params(params: Mapping[str, Any]) -> None:
        if str(params.get("execution_mode") or "").upper() != "APPLY":
            raise ValueError("replay execution_mode must be PLAN or APPLY")
        if params.get("start_date") not in (None, "") or params.get("end_date") not in (None, ""):
            raise ValueError("replay APPLY forbids start_date and end_date")
        if params.get("plan_task_run_id") in (None, "") or not str(params.get("plan_hash") or "").strip():
            raise ValueError("replay APPLY requires plan_task_run_id and plan_hash")

    @staticmethod
    def _maintenance_plan_snapshot(
        *,
        action: MaintenanceActionDefinition,
        plan: MaintenanceExecutionPlan,
        snapshot_state: str | None = None,
    ) -> dict[str, Any]:
        snapshot = {
            "schema_version": 1,
            "action_key": action.key,
            "executor_key": action.executor_key,
            "plan_hash": plan.plan_hash,
            "apply_ready": plan.apply_ready,
            "expected_rows": plan.expected_rows,
            "units": [
                {"unit_key": unit.unit_key, "payload": dict(unit.payload)}
                for unit in plan.units
            ],
            "metadata": dict(plan.metadata),
        }
        if snapshot_state is not None:
            snapshot["snapshot_state"] = snapshot_state
        snapshot["snapshot_integrity_hash"] = TaskRunDispatcher._maintenance_snapshot_hash(snapshot)
        return snapshot

    @staticmethod
    def _maintenance_input_audit_snapshot(
        *,
        action: MaintenanceActionDefinition,
        plan: MaintenanceExecutionPlan,
    ) -> dict[str, Any]:
        metadata = dict(plan.metadata)
        snapshot = {
            "schema_version": 2,
            "snapshot_state": str(metadata.get("audit_state") or "BLOCKED"),
            "action_key": action.key,
            "executor_key": action.executor_key,
            "audit_contract_version": metadata.get("audit_contract_version"),
            "audit_hash": plan.plan_hash,
            "apply_ready": plan.apply_ready,
            "requested_start_date": metadata.get("requested_start_date"),
            "requested_end_date": metadata.get("requested_end_date"),
            "effective_start_date": metadata.get("effective_start_date"),
            "effective_end_date": metadata.get("effective_end_date"),
            "warmup_start_date": metadata.get("warmup_start_date"),
            "ordered_trade_dates": list(metadata.get("ordered_trade_dates") or ()),
            "trade_dates_hash": metadata.get("trade_dates_hash"),
            "hierarchy_version": metadata.get("hierarchy_version"),
            "formula_bundle_version": metadata.get("formula_bundle_version"),
            "template_version": metadata.get("template_version"),
            "target_tables": list(metadata.get("target_tables") or ()),
            "source_coverage_summary": dict(
                metadata.get("source_coverage_summary") or {}
            ),
            "audit_issues": list(metadata.get("audit_issues") or ()),
            "units": [
                {"unit_key": unit.unit_key, "payload": dict(unit.payload)}
                for unit in plan.units
            ],
        }
        snapshot["snapshot_integrity_hash"] = TaskRunDispatcher._maintenance_snapshot_hash(
            snapshot
        )
        return snapshot

    @staticmethod
    def _maintenance_plan_total(plan: MaintenanceExecutionPlan) -> int:
        metadata = plan.metadata if isinstance(plan.metadata, Mapping) else {}
        open_trade_dates = metadata.get("open_trade_dates")
        if isinstance(open_trade_dates, list) and open_trade_dates:
            return len(open_trade_dates)
        gaps = metadata.get("gaps")
        gap_count = len(gaps) if isinstance(gaps, list) else 0
        return max(len(plan.units) + gap_count, 1)

    @staticmethod
    def _maintenance_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
        payload = {
            key: value
            for key, value in snapshot.items()
            if key != "snapshot_integrity_hash"
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _raise_if_task_cancel_requested(session: Session, task_run_id: int) -> None:
        cancel_requested_at, status = session.execute(
            select(TaskRun.cancel_requested_at, TaskRun.status).where(
                TaskRun.id == task_run_id
            )
        ).one()
        if cancel_requested_at is not None or status == "canceling":
            raise IngestionCanceledError("maintenance task cancellation requested")

    def _load_replay_apply_units(
        self,
        *,
        session: Session,
        task_run: TaskRun,
        action: MaintenanceActionDefinition,
        params: Mapping[str, Any],
    ) -> tuple[MaintenanceExecutionUnit, ...]:
        try:
            plan_task_run_id = int(params["plan_task_run_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("plan_task_run_id must be an integer") from exc
        if plan_task_run_id == task_run.id:
            raise ValueError("replay APPLY cannot reference itself")
        plan_task_run = session.get(TaskRun, plan_task_run_id)
        if plan_task_run is None or plan_task_run.status != "success":
            raise ValueError("referenced replay PLAN TaskRun is missing or not successful")
        referenced_action = str((plan_task_run.request_payload_json or {}).get("target_key") or "")
        referenced_params = self._maintenance_params(plan_task_run)
        if (
            plan_task_run.task_type != "maintenance_action"
            or referenced_action != action.key
            or str(referenced_params.get("execution_mode") or "").upper() != "PLAN"
        ):
            raise ValueError("referenced TaskRun is not a PLAN for the same maintenance action")
        snapshot = dict(plan_task_run.plan_snapshot_json or {})
        stored_integrity_hash = str(snapshot.get("snapshot_integrity_hash") or "")
        if not stored_integrity_hash or stored_integrity_hash != self._maintenance_snapshot_hash(snapshot):
            raise ValueError("referenced replay PLAN snapshot integrity check failed")
        submitted_hash = str(params.get("plan_hash") or "").strip()
        if (
            snapshot.get("schema_version") != 1
            or snapshot.get("action_key") != action.key
            or snapshot.get("executor_key") != action.executor_key
            or snapshot.get("plan_hash") != submitted_hash
        ):
            raise ValueError("referenced replay PLAN snapshot or plan_hash is invalid")
        if snapshot.get("apply_ready") is not True:
            raise ValueError("referenced replay PLAN contains source gaps and is not apply-ready")
        metadata = snapshot.get("metadata")
        metadata_start_date = (
            metadata.get("requested_start_date")
            if isinstance(metadata, Mapping)
            else None
        )
        if metadata_start_date in (None, "") and isinstance(metadata, Mapping):
            metadata_start_date = metadata.get("start_date")
        if (
            not isinstance(metadata, Mapping)
            or metadata_start_date != referenced_params.get("start_date")
            or metadata.get("end_date") != referenced_params.get("end_date")
        ):
            raise ValueError("referenced replay PLAN date window does not match its frozen snapshot")
        raw_units = snapshot.get("units")
        if not isinstance(raw_units, list) or not raw_units:
            raise ValueError("referenced replay PLAN has no executable units")
        units = []
        for raw_unit in raw_units:
            if not isinstance(raw_unit, Mapping):
                raise ValueError("referenced replay PLAN unit is invalid")
            unit_key = str(raw_unit.get("unit_key") or "").strip()
            payload = raw_unit.get("payload")
            if not unit_key or not isinstance(payload, Mapping):
                raise ValueError("referenced replay PLAN unit is invalid")
            units.append(MaintenanceExecutionUnit(unit_key=unit_key, payload=dict(payload)))
        return tuple(units)

    @staticmethod
    def _unit_time_input(unit: MaintenanceExecutionUnit) -> dict[str, Any]:
        trade_date = unit.payload.get("trade_date")
        return {"mode": "point", "trade_date": trade_date} if trade_date else {"mode": "none"}

    def _run_dataset_action_plan(
        self,
        session: Session,
        task_run: TaskRun,
        action_request: DatasetActionRequest,
        plan,
    ) -> tuple[int, int, int, dict[str, int], dict[str, list[dict[str, Any]]], str | None]:  # type: ignore[no-untyped-def]
        definition = get_dataset_definition(plan.dataset_key)
        index_period_policy = definition.planning.index_period_raw_policy
        service = DatasetMaintainService(
            session,
            dataset_key=plan.dataset_key,
            run_context=TaskRunIngestionContext(
                session, independent_cancel=plan.execution_context is not None or index_period_policy is not None,
                timeout_seconds=index_period_policy.observation_timeout_seconds if index_period_policy else
                execution_observation_timeout(plan.execution_context),
            ),
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
            if (
                index_period_policy is None
                and not time_input.month
                and definition.date_model.date_axis == "trade_open_day"
                and self._is_closed_trade_date(session, parsed_trade_date)
            ):
                return 0, 0, 0, {}, {}, f"{definition.display_name}：{parsed_trade_date.isoformat()} 非交易日，已跳过维护。"
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
        if plan.execution_context is not None or index_period_policy is not None:
            # Observation writes may have failed; carry the committed business summary
            # through the normal Ops terminal transaction as well.
            task_run.ingestion_diagnostics_json = dict(result.ingestion_diagnostics)
            task_run.rows_deduplicated = result.rows_deduplicated
        rows_saved = int(result.rows_written or 0)
        rows_rejected = int(result.rows_rejected or 0)
        rejected_reason_counts = self._normalize_reason_counts(result.rejected_reason_counts)
        rejected_reason_samples = self._normalize_reason_samples(getattr(result, "rejected_reason_samples", {}))
        light_note = None if index_period_policy is not None else self._refresh_serving_light_if_needed(
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
        return rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, rejected_reason_samples, summary_message

    def _index_period_raw_result(self, session, task_run, node, execution_run):
        diagnostics = dict(execution_run.ingestion_diagnostics_json or {})
        result = diagnostics.get("index_period_raw")
        if not result:
            return "success", None
        result = dict(result)
        missing = result.pop("missing_periods", [])
        diagnostics["index_period_raw"] = result
        execution_run.ingestion_diagnostics_json = diagnostics
        node.ingestion_diagnostics_json = diagnostics
        if execution_run is task_run:
            task_run.unit_done = result["unit_done"]
            task_run.unit_failed = result["unit_failed"]
        if not missing:
            return "success", None

        item = missing[0]
        display_name = get_dataset_definition(item["dataset_key"]).display_name
        code_text = f' {item["ts_code"]}' if item["ts_code"] else ""
        issue = self._record_issue(
            session, task_run=task_run, node_id=node.id, code=MISSING_PERIOD_CODE,
            title=f"{display_name}正式源缺期",
            operator_message=f'{display_name}{code_text} 有 {len(missing)} 个期末无源数据，首个缺期为 {item["trade_date"]}。完整列表见任务诊断。',
            suggested_action="等待源端发布后，按原范围重试。",
            technical_message=f"{display_name}{code_text} 正式源无数据，缺 {len(missing)} 期。",
            source_phase="source_client", severity="error", technical_payload={"missing_periods": missing},
        )
        node.issue_id = issue.id
        return ("partial_success" if result["unit_done"] else "failed"), issue

    @staticmethod
    def _restore_index_period_raw_progress(task_run, exc):
        progress = getattr(exc, "index_period_raw_progress", None)
        if progress is None:
            return
        for name in ("rows_fetched", "rows_saved", "rows_rejected", "unit_done", "unit_failed", "unit_total"):
            setattr(task_run, name, progress[name])
        task_run.ingestion_diagnostics_json = progress["ingestion_diagnostics"]
        if task_run.unit_total:
            task_run.progress_percent = int(100 * (task_run.unit_done + task_run.unit_failed) / task_run.unit_total)

    @staticmethod
    def _index_period_raw_error_message(exc):
        if not getattr(exc, "index_period_raw_progress", None) or not isinstance(exc, IngestionError):
            return None
        error = exc.structured_error
        details = error.details
        dataset = get_dataset_definition(details["dataset_key"]).display_name
        code = details.get("row", {}).get("ts_code") or details.get("ts_code") or details.get("actual_ts_code")
        scope = f'{dataset} {details["trade_date"]}' + (f" {code}" if code else "")
        if error.error_code == "normalize.unit_date_mismatch":
            return f'{scope} 源数据日期错误，预期 {details["expected"]}，实际 {details["actual"]}。'
        if "limit_bytes" in details:
            return f'{scope} {error.message}，采样 {details["actual_bytes"]} 字节，上限 {details["limit_bytes"]} 字节。'
        if "limit_seconds" in details:
            return f'{scope} {error.message}，已用 {details["actual_seconds"]} 秒，上限 {details["limit_seconds"]} 秒。'
        if error.error_code == "index_period_raw.source_deadline_exceeded":
            actual_ms = details.get("elapsed_ms")
            limit = details.get("total_timeout_seconds")
            if actual_ms is not None and limit is not None:
                return f"{scope} {error.message}，已用 {actual_ms / 1000:.3f} 秒，上限 {limit:.3f} 秒。"
        return f"{scope} {error.message}"

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
                ann_date=self._optional_date(time_payload.get("ann_date")),
                start_date=self._optional_date(time_payload.get("start_date")),
                end_date=self._optional_date(time_payload.get("end_date")),
                month=self._optional_text(time_payload.get("month")),
                start_month=self._optional_text(time_payload.get("start_month")),
                end_month=self._optional_text(time_payload.get("end_month")),
                date_field=self._optional_text(time_payload.get("date_field")),
            ),
            filters=filters,
            trigger_source=dataset_action_trigger_source(resource_key, task_run.trigger_source),
            requested_by_user_id=task_run.requested_by_user_id,
            schedule_id=task_run.schedule_id,
            run_id=task_run.id,
            execution_context=(task_run.request_payload_json or {}).get('execution_context'),
        )

    def _prepare_dataset_action_request(self, session: Session, request: DatasetActionRequest) -> DatasetActionRequest:
        time_input = request.time_input
        if time_input.mode == "point" and time_input.trade_date is None and time_input.ann_date is not None:
            return replace(request, time_input=replace(time_input, trade_date=time_input.ann_date, date_field="ann_date"))
        if time_input.mode != "point" or time_input.trade_date is not None or time_input.month:
            return request
        trade_date = self._resolve_default_trade_date(session)
        if trade_date is None:
            raise ValueError("未找到可用日期，请先同步日历或手动指定日期。")
        return replace(request, time_input=replace(time_input, trade_date=trade_date))

    @staticmethod
    def _dataset_time_input_payload(time_input: DatasetTimeInput) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": time_input.mode}
        for key in ("trade_date", "ann_date", "start_date", "end_date"):
            value = getattr(time_input, key)
            if value is not None:
                payload[key] = value.isoformat()
        for key in ("month", "start_month", "end_month", "date_field"):
            value = getattr(time_input, key)
            if value not in (None, ""):
                payload[key] = value
        return payload

    @staticmethod
    def _plan_snapshot(plan) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        units = list(plan.units or ())
        return {
            "plan_id": plan.plan_id,
            "dataset_key": plan.dataset_key,
            "run_profile": plan.run_profile,
            "unit_count": plan.planning.unit_count,
            "execution_context": plan.execution_context,
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
        raise ValueError(f"不支持的系统维护执行器：{action.executor_key}")

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
        rows_deduplicated: int | None = None,
        ingestion_diagnostics: dict[str, Any] | None = None,
        rejected_reason_counts: dict[str, int] | None = None,
        rejected_reason_samples: dict[str, list[dict[str, Any]]] | None = None,
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
        if rows_deduplicated is not None:
            node.rows_deduplicated = rows_deduplicated
        if ingestion_diagnostics is not None:
            node.ingestion_diagnostics_json = dict(ingestion_diagnostics)
        if rejected_reason_counts is not None:
            node.rejected_reason_counts_json = TaskRunDispatcher._normalize_reason_counts(rejected_reason_counts)
        if rejected_reason_samples is not None:
            node.rejected_reason_samples_json = TaskRunDispatcher._normalize_reason_samples(rejected_reason_samples)
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

    @staticmethod
    def _merge_diagnostics(target: dict[str, Any], source: Mapping[str, Any] | None) -> None:
        if not isinstance(source, Mapping):
            return
        for key, value in source.items():
            if isinstance(value, bool):
                target[key] = value
            elif isinstance(value, int | float):
                target[key] = int(target.get(key, 0) or 0) + value
            elif key == "last_cursor" and isinstance(value, Mapping):
                target[key] = dict(value)
            else:
                target[key] = value

    @staticmethod
    def _normalize_reason_samples(value: dict[str, list[dict[str, Any]]] | None) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, list[dict[str, Any]]] = {}
        for raw_key, raw_samples in value.items():
            key = str(raw_key or "").strip()
            if not key or not isinstance(raw_samples, list):
                continue
            bucket: list[dict[str, Any]] = []
            for sample in raw_samples:
                if len(bucket) >= 3:
                    break
                if isinstance(sample, dict):
                    bucket.append(dict(sample))
            if bucket:
                normalized[key] = bucket
        return normalized

    @staticmethod
    def _merge_reason_samples(
        target: dict[str, list[dict[str, Any]]],
        source: dict[str, list[dict[str, Any]]] | None,
    ) -> None:
        for key, samples in TaskRunDispatcher._normalize_reason_samples(source).items():
            bucket = target.setdefault(key, [])
            for sample in samples:
                if len(bucket) >= 3:
                    break
                bucket.append(dict(sample))

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
        technical_payload: Mapping[str, Any] | None = None,
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
        technical_payload_json = {
            "source_phase": source_phase,
            "node_id": node_id,
            "task_run_id": task_run.id,
        }
        if technical_payload:
            technical_payload_json.update(dict(technical_payload))
        issue = TaskRunIssue(
            task_run_id=task_run.id,
            node_id=node_id,
            severity=severity,
            code=code,
            title=title,
            operator_message=truncate_text(operator_message, self.MAX_OPERATOR_MESSAGE_LENGTH),
            suggested_action=truncate_text(suggested_action, self.MAX_OPERATOR_MESSAGE_LENGTH),
            technical_message=truncate_text(technical_message, self.MAX_TECHNICAL_MESSAGE_LENGTH),
            technical_payload_json=technical_payload_json,
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
    def _technical_payload_for_exception(exc: Exception) -> dict[str, Any] | None:
        if not isinstance(exc, IngestionError):
            return None
        return {"structured_error": structured_error_payload(exc.structured_error)}

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
