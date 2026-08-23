from __future__ import annotations

from src.db import get_session_factory
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.runtime.worker_lane import WorkerLane

from .sector_heat_task_executor import SectorHeatTaskExecutor
from .news_stock_linking_task_executor import NewsStockLinkingTaskExecutor


def _build_worker(*, lane: WorkerLane, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    resolved_session_factory = session_factory or get_session_factory()
    heat_executor = SectorHeatTaskExecutor(session_factory=resolved_session_factory)
    news_stock_linking_executor = NewsStockLinkingTaskExecutor(session_factory=resolved_session_factory)
    dispatcher = TaskRunDispatcher(
        maintenance_executors={
            "wealth_sector_heat": heat_executor,
            "news_stock_linking": news_stock_linking_executor,
        },
    )
    return OperationsWorker(dispatcher=dispatcher, lane=lane)


def build_operations_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.GENERAL, session_factory=session_factory)


def build_stk_mins_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.STK_MINS, session_factory=session_factory)


def build_index_mins_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.INDEX_MINS, session_factory=session_factory)
