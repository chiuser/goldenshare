from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.ops.models.ops.task_run import TaskRun
from src.ops.runtime.worker_lane import WorkerLane, lane_matches_values, lane_task_filter


def test_lane_matches_values_covers_general_and_dedicated_lanes() -> None:
    assert lane_matches_values(WorkerLane.GENERAL, task_type="workflow", resource_key=None)
    assert lane_matches_values(WorkerLane.GENERAL, task_type="maintenance_action", resource_key=None)
    assert lane_matches_values(WorkerLane.GENERAL, task_type="dataset_action", resource_key="daily")
    assert not lane_matches_values(WorkerLane.GENERAL, task_type="dataset_action", resource_key="stk_mins")
    assert not lane_matches_values(WorkerLane.GENERAL, task_type="dataset_action", resource_key="index_mins")
    assert not lane_matches_values(WorkerLane.GENERAL, task_type="qtf_experiment", resource_key="sector_heat_research")
    assert lane_matches_values(WorkerLane.STK_MINS, task_type="dataset_action", resource_key="stk_mins")
    assert not lane_matches_values(WorkerLane.STK_MINS, task_type="dataset_action", resource_key="index_mins")
    assert lane_matches_values(WorkerLane.INDEX_MINS, task_type="dataset_action", resource_key="index_mins")
    assert not lane_matches_values(WorkerLane.INDEX_MINS, task_type="workflow", resource_key=None)
    assert lane_matches_values(WorkerLane.QTF, task_type="qtf_experiment", resource_key="sector_heat_research")
    assert not lane_matches_values(WorkerLane.QTF, task_type="dataset_action", resource_key="stk_mins")


def test_general_lane_sql_keeps_null_resource_keys_and_excludes_minute_tasks() -> None:
    statement = select(TaskRun.id).where(lane_task_filter(WorkerLane.GENERAL))
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "resource_key IS NULL" in sql
    assert "task_type !=" in sql
    assert "NOT (ops.task_run.task_type =" in sql
    assert "resource_key IN" in sql


def test_dedicated_lane_sql_matches_only_its_dataset() -> None:
    statement = select(TaskRun.id).where(lane_task_filter(WorkerLane.STK_MINS))
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "task_type = %(task_type_1)s" in sql
    assert "resource_key = %(resource_key_1)s" in sql
    assert "index_mins" not in sql


def test_qtf_lane_sql_isolated_from_general_and_minute_work() -> None:
    qtf_sql = str(select(TaskRun.id).where(lane_task_filter(WorkerLane.QTF)).compile(dialect=postgresql.dialect()))
    general_sql = str(select(TaskRun.id).where(lane_task_filter(WorkerLane.GENERAL)).compile(dialect=postgresql.dialect()))

    assert "task_type =" in qtf_sql
    assert "resource_key" not in qtf_sql
    assert "task_type !=" in general_sql
