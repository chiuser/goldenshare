from __future__ import annotations

from src.ops.models.ops.config_revision import ConfigRevision
from src.ops.models.ops.job_schedule import JobSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode


def test_ops_control_plane_models_expose_primary_keys_and_indexes() -> None:
    assert [column.name for column in JobSchedule.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in JobSchedule.__table__.indexes} == {
        "idx_job_schedule_spec_type_spec_key",
        "idx_job_schedule_status_next_run_at",
    }

    assert [column.name for column in TaskRun.__table__.primary_key.columns] == ["id"]
    assert "current_object_json" in TaskRun.__table__.columns
    assert "current_context_json" not in TaskRun.__table__.columns
    assert {index.name for index in TaskRun.__table__.indexes} == {
        "idx_task_run_resource_requested_at",
        "idx_task_run_schedule_requested_at",
        "idx_task_run_status_requested_at",
    }

    assert [column.name for column in TaskRunNode.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in TaskRunNode.__table__.indexes} == {
        "idx_task_run_node_run_sequence",
        "idx_task_run_node_run_status",
    }

    assert [column.name for column in TaskRunIssue.__table__.primary_key.columns] == ["id"]
    assert "object_json" in TaskRunIssue.__table__.columns
    assert {index.name for index in TaskRunIssue.__table__.indexes} == {
        "idx_task_run_issue_code_occurred",
        "idx_task_run_issue_run_occurred",
    }

    assert [column.name for column in ConfigRevision.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in ConfigRevision.__table__.indexes} == {"idx_config_revision_object_changed_at"}
