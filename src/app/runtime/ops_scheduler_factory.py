from __future__ import annotations

from datetime import time

from src.db import get_session_factory
from src.ops.action_catalog import get_maintenance_action
from src.ops.runtime.scheduler import OperationsScheduler
from src.ops.services.operations_schedule_service import HEAT_DAILY_ACTION_KEY
from src.ops.services.runtime_service import OpsRuntimeCommandService
from src.ops.services.sector_heat_upstream_readiness_service import SectorHeatUpstreamReadinessService

from .sector_heat_readiness_evaluator import SectorHeatReadinessEvaluator


def build_operations_scheduler(*, session_factory=None) -> OperationsScheduler:  # type: ignore[no-untyped-def]
    resolved_session_factory = session_factory or get_session_factory()
    action = get_maintenance_action(HEAT_DAILY_ACTION_KEY)
    if action is None:
        raise RuntimeError("Heat 自动任务 action contract 不存在")
    not_before = time.fromisoformat(str(action.readiness_policy["upstream_not_before_local_time"]))
    return OperationsScheduler(
        heat_readiness_evaluator=SectorHeatReadinessEvaluator(
            session_factory=resolved_session_factory,
            upstream_service=SectorHeatUpstreamReadinessService(not_before_local_time=not_before),
        )
    )


def build_ops_runtime_command_service(*, session_factory=None) -> OpsRuntimeCommandService:  # type: ignore[no-untyped-def]
    from .ops_worker_factory import build_operations_worker

    resolved_session_factory = session_factory or get_session_factory()
    return OpsRuntimeCommandService(
        scheduler=build_operations_scheduler(session_factory=resolved_session_factory),
        worker=build_operations_worker(session_factory=resolved_session_factory),
    )
