from __future__ import annotations

from collections.abc import Mapping
from datetime import time

from src.db import get_session_factory
from src.ops.action_catalog import get_maintenance_action
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.services.operations_schedule_service import (
    HEAT_DAILY_ACTION_KEY,
    SECTOR_ANALYSIS_DAILY_ACTION_KEY,
)
from src.ops.services.runtime_service import OpsRuntimeCommandService
from src.ops.services.sector_heat_upstream_readiness_service import SectorHeatUpstreamReadinessService

from .sector_heat_readiness_evaluator import SectorHeatReadinessEvaluator
from .sector_analysis_daily_readiness_evaluator import SectorAnalysisDailyReadinessEvaluator


def build_operations_scheduler(*, session_factory=None) -> OperationsScheduler:  # type: ignore[no-untyped-def]
    resolved_session_factory = session_factory or get_session_factory()
    action = get_maintenance_action(HEAT_DAILY_ACTION_KEY)
    if action is None:
        raise RuntimeError("Heat 自动任务 action contract 不存在")
    raw_workflow_not_before = action.readiness_policy.get(
        "upstream_workflow_not_before_local_times"
    )
    if not isinstance(raw_workflow_not_before, Mapping):
        raise RuntimeError("Heat 自动任务缺少按上游工作流区分的时间契约")
    try:
        workflow_not_before = {
            str(workflow_key): time.fromisoformat(str(not_before))
            for workflow_key, not_before in raw_workflow_not_before.items()
        }
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Heat 自动任务上游时间契约格式无效") from exc
    return OperationsScheduler(
        readiness_evaluators={
            HEAT_DAILY_ACTION_KEY: SectorHeatReadinessEvaluator(
                session_factory=resolved_session_factory,
                upstream_service=SectorHeatUpstreamReadinessService(
                    workflow_not_before_local_times=workflow_not_before
                ),
            ),
            SECTOR_ANALYSIS_DAILY_ACTION_KEY: SectorAnalysisDailyReadinessEvaluator(
                session_factory=resolved_session_factory,
            ),
        },
    )


def build_ops_runtime_command_service(*, session_factory=None) -> OpsRuntimeCommandService:  # type: ignore[no-untyped-def]
    from .ops_worker_factory import build_operations_worker

    resolved_session_factory = session_factory or get_session_factory()
    return OpsRuntimeCommandService(
        scheduler=build_operations_scheduler(session_factory=resolved_session_factory),
        worker=build_operations_worker(session_factory=resolved_session_factory),
    )
