from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.services.operations_task_run_reconciliation_service import OperationsTaskRunReconciliationService


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        TaskRun.__table__.create(connection)
        TaskRunIssue.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def build_task_run(**overrides) -> TaskRun:  # type: ignore[no-untyped-def]
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
    values = {
        "task_type": "dataset_action",
        "resource_key": "daily",
        "action": "maintain",
        "title": "股票日线",
        "trigger_source": "manual",
        "status": "running",
        "requested_at": now - timedelta(hours=2),
        "queued_at": now - timedelta(hours=2),
        "started_at": now - timedelta(hours=2),
        "time_input_json": {},
        "filters_json": {},
        "request_payload_json": {},
        "plan_snapshot_json": {},
        "current_object_json": {},
        "created_at": now - timedelta(hours=2),
        "updated_at": now - timedelta(hours=2),
    }
    values.update(overrides)
    return TaskRun(**values)


def test_preview_stale_task_runs_returns_only_stale_open_items(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)

    stale = build_task_run()
    healthy = build_task_run(
        resource_key="adj_factor",
        requested_at=now - timedelta(minutes=20),
        queued_at=now - timedelta(minutes=20),
        started_at=now - timedelta(minutes=20),
    )
    done = build_task_run(
        status="success",
        requested_at=now - timedelta(hours=3),
        queued_at=now - timedelta(hours=3),
        started_at=now - timedelta(hours=3),
        ended_at=now - timedelta(hours=2, minutes=30),
    )
    db_session.add_all([stale, healthy, done])
    db_session.commit()

    items = OperationsTaskRunReconciliationService().preview_stale_task_runs(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    assert [(item.id, item.previous_status, item.new_status) for item in items] == [
        (stale.id, "running", "failed"),
    ]


def test_reconcile_stale_task_runs_marks_cancel_requested_as_canceled(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
    task_run = build_task_run(cancel_requested_at=now - timedelta(hours=1))
    db_session.add(task_run)
    db_session.commit()

    reconciled = OperationsTaskRunReconciliationService().reconcile_stale_task_runs(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    db_session.refresh(task_run)
    assert [(item.id, item.new_status) for item in reconciled] == [(task_run.id, "canceled")]
    assert task_run.status == "canceled"
    assert task_run.canceled_at is not None
    assert task_run.canceled_at.replace(tzinfo=timezone.utc) == now
    assert task_run.status_reason_code == "stale_cancel_reconciled"


def test_reconcile_stale_task_runs_records_issue_for_failed_item(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
    task_run = build_task_run()
    db_session.add(task_run)
    db_session.commit()

    reconciled = OperationsTaskRunReconciliationService().reconcile_stale_task_runs(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    db_session.refresh(task_run)
    issue = db_session.get(TaskRunIssue, task_run.primary_issue_id)
    assert [(item.id, item.new_status) for item in reconciled] == [(task_run.id, "failed")]
    assert task_run.status == "failed"
    assert task_run.status_reason_code == "stale_task_run"
    assert issue is not None
    assert issue.code == "stale_task_run"
