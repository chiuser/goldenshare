from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.job_execution_event import JobExecutionEvent
from src.ops.models.ops.sync_run_log import SyncRunLog
from src.ops.services.operations_execution_reconciliation_service import OperationsExecutionReconciliationService


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
        JobExecution.__table__.create(connection)
        JobExecutionEvent.__table__.create(connection)
        SyncRunLog.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_preview_stale_executions_returns_only_stale_open_items(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)

    stale = JobExecution(
        spec_type="job",
        spec_key="backfill_equity_series.daily",
        trigger_source="manual",
        status="running",
        requested_at=now - timedelta(hours=2),
        queued_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        params_json={},
    )
    healthy = JobExecution(
        spec_type="job",
        spec_key="backfill_equity_series.adj_factor",
        trigger_source="manual",
        status="running",
        requested_at=now - timedelta(minutes=20),
        queued_at=now - timedelta(minutes=20),
        started_at=now - timedelta(minutes=20),
        params_json={},
        last_progress_at=now - timedelta(minutes=2),
        progress_message="still moving",
    )
    done = JobExecution(
        spec_type="job",
        spec_key="sync_daily.daily",
        trigger_source="scheduled",
        status="success",
        requested_at=now - timedelta(hours=3),
        queued_at=now - timedelta(hours=3),
        started_at=now - timedelta(hours=3),
        ended_at=now - timedelta(hours=2, minutes=30),
        params_json={},
    )
    db_session.add_all([stale, healthy, done])
    db_session.commit()

    items = OperationsExecutionReconciliationService().preview_stale_executions(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    assert [(item.id, item.previous_status, item.new_status) for item in items] == [
        (stale.id, "running", "failed"),
    ]


def test_reconcile_stale_executions_marks_cancel_requested_as_canceled(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
    execution = JobExecution(
        spec_type="job",
        spec_key="backfill_equity_series.daily",
        trigger_source="manual",
        status="running",
        requested_at=now - timedelta(hours=2),
        queued_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        cancel_requested_at=now - timedelta(hours=1),
        params_json={},
    )
    db_session.add(execution)
    db_session.commit()

    reconciled = OperationsExecutionReconciliationService().reconcile_stale_executions(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    db_session.refresh(execution)
    assert [(item.id, item.new_status) for item in reconciled] == [(execution.id, "canceled")]
    assert execution.status == "canceled"
    assert execution.canceled_at is not None
    assert execution.canceled_at.replace(tzinfo=timezone.utc) == now
    assert execution.summary_message == "任务在停止后未正常收尾，系统已将状态修正为已取消。"
    last_event = db_session.query(JobExecutionEvent).filter_by(execution_id=execution.id).order_by(JobExecutionEvent.id.desc()).first()
    assert last_event is not None
    assert last_event.event_type == "canceled"


def test_reconcile_stale_executions_uses_recent_log_activity_to_keep_active_item(db_session: Session) -> None:
    now = datetime(2026, 4, 1, 1, 0, tzinfo=timezone.utc)
    execution = JobExecution(
        spec_type="job",
        spec_key="backfill_equity_series.daily",
        trigger_source="manual",
        status="running",
        requested_at=now - timedelta(hours=2),
        queued_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
        params_json={},
    )
    db_session.add(execution)
    db_session.flush()
    db_session.add(
        SyncRunLog(
            execution_id=execution.id,
            job_name="sync_daily",
            run_type="manual",
            status="RUNNING",
            started_at=now - timedelta(minutes=3),
            ended_at=None,
            rows_fetched=10,
            rows_written=10,
            message="still alive",
        )
    )
    db_session.commit()

    reconciled = OperationsExecutionReconciliationService().reconcile_stale_executions(
        db_session,
        stale_for_minutes=30,
        now=now,
    )

    db_session.refresh(execution)
    assert reconciled == []
    assert execution.status == "running"
