from __future__ import annotations

from src.models.ops.config_revision import ConfigRevision
from src.models.ops.job_execution import JobExecution
from src.models.ops.job_execution_event import JobExecutionEvent
from src.models.ops.job_execution_step import JobExecutionStep
from src.models.ops.job_schedule import JobSchedule
from src.models.ops.sync_run_log import SyncRunLog


def test_ops_control_plane_models_expose_primary_keys_and_indexes() -> None:
    assert [column.name for column in JobSchedule.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in JobSchedule.__table__.indexes} == {
        "idx_job_schedule_spec_type_spec_key",
        "idx_job_schedule_status_next_run_at",
    }

    assert [column.name for column in JobExecution.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in JobExecution.__table__.indexes} == {
        "idx_job_execution_schedule_id_requested_at",
        "idx_job_execution_spec_requested_at",
        "idx_job_execution_status_requested_at",
    }

    assert [column.name for column in JobExecutionStep.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in JobExecutionStep.__table__.indexes} == {
        "idx_job_execution_step_execution_sequence",
        "idx_job_execution_step_execution_status",
    }

    assert [column.name for column in JobExecutionEvent.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in JobExecutionEvent.__table__.indexes} == {
        "idx_job_execution_event_execution_occurred_at",
        "idx_job_execution_event_step_occurred_at",
    }

    assert [column.name for column in ConfigRevision.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in ConfigRevision.__table__.indexes} == {"idx_config_revision_object_changed_at"}


def test_sync_run_log_supports_optional_execution_link() -> None:
    assert "execution_id" in SyncRunLog.__table__.columns
    assert {index.name for index in SyncRunLog.__table__.indexes} == {
        "idx_sync_run_log_execution_id",
        "idx_sync_run_log_job_name_started_at",
    }
