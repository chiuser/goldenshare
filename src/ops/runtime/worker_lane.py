from __future__ import annotations

from enum import StrEnum

from sqlalchemy import and_, or_

from src.ops.models.ops.task_run import TaskRun


class WorkerLane(StrEnum):
    GENERAL = "general"
    STK_MINS = "stk_mins"
    INDEX_MINS = "index_mins"
    QTF = "qtf"


MINUTE_DATASET_KEYS = frozenset({"stk_mins", "index_mins"})


def lane_matches_values(
    lane: WorkerLane,
    *,
    task_type: str | None,
    resource_key: str | None,
) -> bool:
    if lane is WorkerLane.GENERAL:
        return task_type != "qtf_experiment" and not (
            task_type == "dataset_action" and resource_key in MINUTE_DATASET_KEYS
        )
    if lane is WorkerLane.STK_MINS:
        return task_type == "dataset_action" and resource_key == "stk_mins"
    if lane is WorkerLane.INDEX_MINS:
        return task_type == "dataset_action" and resource_key == "index_mins"
    if lane is WorkerLane.QTF:
        return task_type == "qtf_experiment"
    raise ValueError(f"unsupported worker lane: {lane}")


def lane_task_filter(lane: WorkerLane):  # type: ignore[no-untyped-def]
    minute_task = and_(
        TaskRun.task_type == "dataset_action",
        TaskRun.resource_key.in_(MINUTE_DATASET_KEYS),
    )
    if lane is WorkerLane.GENERAL:
        # Keep NULL resource keys eligible for workflow and maintenance tasks.
        return and_(
            TaskRun.task_type != "qtf_experiment",
            or_(
                TaskRun.task_type != "dataset_action",
                TaskRun.task_type.is_(None),
                TaskRun.resource_key.is_(None),
                ~minute_task,
            ),
        )
    if lane is WorkerLane.STK_MINS:
        return and_(
            TaskRun.task_type == "dataset_action",
            TaskRun.resource_key == "stk_mins",
        )
    if lane is WorkerLane.INDEX_MINS:
        return and_(
            TaskRun.task_type == "dataset_action",
            TaskRun.resource_key == "index_mins",
        )
    if lane is WorkerLane.QTF:
        return TaskRun.task_type == "qtf_experiment"
    raise ValueError(f"unsupported worker lane: {lane}")
