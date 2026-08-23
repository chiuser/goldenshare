from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.db import get_session_factory
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.runtime.worker_lane import WorkerLane

from .sector_heat_task_executor import SectorHeatTaskExecutor
from .news_stock_linking_task_executor import NewsStockLinkingTaskExecutor
from .qtf_task_executor import QtfTaskExecutor


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RELEASE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _validate_qtf_release_commit(value: str) -> str:
    release_commit = value.strip()
    if not _RELEASE_COMMIT_PATTERN.fullmatch(release_commit):
        raise RuntimeError("QTF worker 无法确认有效的部署 Git commit。")
    return release_commit


def _resolve_qtf_release_commit(*, repository_root: Path = _REPOSITORY_ROOT) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("QTF worker 无法读取部署 Git commit。") from exc
    return _validate_qtf_release_commit(completed.stdout)


def _build_worker(
    *,
    lane: WorkerLane,
    session_factory=None,  # type: ignore[no-untyped-def]
    qtf_release_commit: str | None = None,
) -> OperationsWorker:
    resolved_session_factory = session_factory or get_session_factory()
    heat_executor = SectorHeatTaskExecutor(session_factory=resolved_session_factory)
    news_stock_linking_executor = NewsStockLinkingTaskExecutor(session_factory=resolved_session_factory)
    if lane is WorkerLane.QTF:
        if qtf_release_commit is None:
            raise RuntimeError("QTF worker 缺少已冻结的部署 Git commit。")
        external_executors = {
            "qtf_experiment": QtfTaskExecutor(
                session_factory=resolved_session_factory,
                release_commit=qtf_release_commit,
            )
        }
    else:
        external_executors = {}
    dispatcher = TaskRunDispatcher(
        maintenance_executors={
            "wealth_sector_heat": heat_executor,
            "news_stock_linking": news_stock_linking_executor,
        },
        external_executors=external_executors,
    )
    return OperationsWorker(dispatcher=dispatcher, lane=lane)


def build_operations_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.GENERAL, session_factory=session_factory)


def build_stk_mins_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.STK_MINS, session_factory=session_factory)


def build_index_mins_worker(*, session_factory=None) -> OperationsWorker:  # type: ignore[no-untyped-def]
    return _build_worker(lane=WorkerLane.INDEX_MINS, session_factory=session_factory)


def build_qtf_worker(
    *,
    session_factory=None,  # type: ignore[no-untyped-def]
    release_commit: str | None = None,
) -> OperationsWorker:
    resolved_release_commit = (
        _resolve_qtf_release_commit()
        if release_commit is None
        else _validate_qtf_release_commit(release_commit)
    )
    return _build_worker(
        lane=WorkerLane.QTF,
        session_factory=session_factory,
        qtf_release_commit=resolved_release_commit,
    )
