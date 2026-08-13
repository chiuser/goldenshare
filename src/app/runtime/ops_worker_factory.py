from __future__ import annotations

from src.db import get_session_factory
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker

from .sector_heat_task_executor import SectorHeatTaskExecutor


def build_operations_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    resolved_session_factory = session_factory or get_session_factory()
    heat_executor = SectorHeatTaskExecutor(session_factory=resolved_session_factory)
    dispatcher = TaskRunDispatcher(maintenance_executors={"wealth_sector_heat": heat_executor})
    return OperationsWorker(dispatcher=dispatcher)
