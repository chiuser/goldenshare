"""Maintenance runtime regression using isolated SQLite business and Ops tables."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
)
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher, TaskRunDispatchOutcome
from src.ops.runtime.worker import OperationsWorker
from src.ops.services.news_stock_linking_service import NEWS_STOCK_LINKING_ACTION_KEY


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        for model in (TaskRun, TaskRunNode, TaskRunIssue):
            model.__table__.create(connection)
        connection.exec_driver_sql(
            "CREATE TABLE business_commits (unit_key TEXT, row_number INTEGER, "
            "PRIMARY KEY (unit_key, row_number))"
        )
    with Session(engine) as value:
        yield value
    engine.dispose()


def task(session, **overrides):
    values = dict(
        task_type="maintenance_action", action="maintain", title="维护进度回归",
        trigger_source="manual", status="queued", requested_at=datetime.now(timezone.utc),
        request_payload_json={"target_key": NEWS_STOCK_LINKING_ACTION_KEY},
        time_input_json={}, filters_json={},
    )
    values.update(overrides)
    value = TaskRun(**values)
    session.add(value)
    session.commit()
    return value


class Executor:
    """Uses the existing maintenance protocol; literal counts are test expectations."""

    def __init__(self, bind, *, ending="success", partial=False):
        self.bind = bind
        self.ending = ending
        self.partial = partial

    def plan(self, request):
        return MaintenanceExecutionPlan(
            plan_hash="maintenance-progress-fixture",
            units=tuple(
                MaintenanceExecutionUnit(unit_key=key, payload={})
                for key in ("first", "second")
            ),
        )

    def execute_unit(self, unit):
        raise AssertionError("The task-aware protocol must be used")

    def commit_rows(self, key, count):
        with Session(self.bind) as business:
            business.execute(
                text("INSERT INTO business_commits VALUES (:key, :number)"),
                [{"key": key, "number": n} for n in range(count)],
            )
            business.commit()

    def execute_unit_for_task_run(self, unit, *, context):
        if unit.unit_key == "second" and self.ending != "success":
            if self.partial:
                self.commit_rows("second", 3)
                context.run_context.update_progress(
                    run_id=context.task_run_id, unit_done=1, unit_failed=0, total=2,
                    message="第二个单元已提交部分数据", rows_fetched=9, rows_saved=6,
                    rows_rejected=1, rows_deduplicated=2,
                    ingestion_diagnostics={"phase": "second-partial"},
                )
            if self.ending == "cancel":
                raise IngestionCanceledError("fixture cancellation")
            raise RuntimeError("fixture execution failure")
        first = unit.unit_key == "first"
        self.commit_rows(unit.unit_key, 3 if first else 4)
        return MaintenanceExecutionResult(
            rows_fetched=5 if first else 7, rows_saved=3 if first else 4,
            rows_rejected=1 if first else 0,
            metadata={"rows_deduplicated": 1, "phase": unit.unit_key},
        )


def run(session, executor):
    worker = OperationsWorker(TaskRunDispatcher(
        maintenance_executors={"news_stock_linking": executor},
    ))
    return worker.run_next(session)


@pytest.mark.parametrize("ending,status", [("cancel", "canceled"), ("failure", "failed")])
@pytest.mark.parametrize("partial", [False, True])
def test_cancel_or_failure_keeps_committed_progress(session, ending, status, partial):
    task(session)
    result = run(session, Executor(session.get_bind(), ending=ending, partial=partial))
    assert result.status == status
    assert result.rows_fetched == (9 if partial else 5)
    assert result.rows_saved == (6 if partial else 3)
    assert result.rows_rejected == 1
    assert result.rows_deduplicated == (2 if partial else 1)
    assert result.unit_done == 1
    assert result.progress_percent == 50
    assert result.ingestion_diagnostics_json["phase"] == ("second-partial" if partial else "first")
    assert session.scalar(text("SELECT count(*) FROM business_commits")) == (6 if partial else 3)
    nodes = session.scalars(select(TaskRunNode).order_by(TaskRunNode.sequence_no)).all()
    assert [node.status for node in nodes] == ["success", status]
    assert nodes[0].rows_saved == 3
    assert nodes[1].rows_saved == (6 if partial else 0)


def test_success_retains_existing_result_semantics(session):
    task(session)
    result = run(session, Executor(session.get_bind()))
    assert (result.status, result.rows_fetched, result.rows_saved) == ("success", 12, 7)
    assert (result.rows_rejected, result.rows_deduplicated) == (1, 2)
    assert (result.unit_done, result.unit_total, result.progress_percent) == (2, 2, 100)
    assert session.scalar(text("SELECT count(*) FROM business_commits")) == 7
    assert [n.rows_saved for n in session.scalars(select(TaskRunNode).order_by(TaskRunNode.sequence_no))] == [3, 4]


def test_business_commit_survives_progress_commit_failure(session, monkeypatch):
    task(session)
    original = session.commit
    failed = False

    def fail_once():
        nonlocal failed
        if not failed and any(isinstance(row, TaskRunNode) and row.status == "success" for row in session.dirty):
            failed = True
            raise SQLAlchemyError("fixture progress commit failure")
        return original()

    monkeypatch.setattr(session, "commit", fail_once)
    result = run(session, Executor(session.get_bind()))
    assert failed
    assert result.status == "failed"
    assert (result.rows_fetched, result.rows_saved, result.rows_rejected, result.rows_deduplicated) == (5, 3, 1, 1)
    assert result.unit_done == 1
    assert session.scalar(text("SELECT count(*) FROM business_commits")) == 3
    node = session.scalar(select(TaskRunNode))
    assert (node.status, node.rows_saved) == ("failed", 3)


def test_new_node_failure_does_not_change_completed_node(session, monkeypatch):
    task(session)
    original = TaskRunDispatcher._create_node

    def fail_second(*args, **kwargs):
        if kwargs["node_key"] == "second":
            raise RuntimeError("fixture node creation failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(TaskRunDispatcher, "_create_node", staticmethod(fail_second))
    result = run(session, Executor(session.get_bind()))
    assert (result.status, result.rows_saved, result.unit_done) == ("failed", 3, 1)
    node = session.scalar(select(TaskRunNode))
    assert (node.status, node.rows_saved) == ("success", 3)


@pytest.mark.parametrize("task_type,expected", [("maintenance_action", 6), ("dataset_action", 0)])
def test_failure_without_new_summary_preserves_only_maintenance_progress(session, task_type, expected):
    value = task(session, task_type=task_type, status="running", rows_saved=6,
                 ingestion_diagnostics_json={"phase": "committed"})
    result = OperationsWorker()._finalize_task_run(session, value.id, TaskRunDispatchOutcome(status="failed"))
    assert result.rows_saved == expected
    assert result.ingestion_diagnostics_json == ({"phase": "committed"} if expected else {})


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_worker_closes_active_node_without_copying_whole_task_counts(session, status):
    value = task(session, status="running", rows_saved=6)
    node = TaskRunNode(
        task_run_id=value.id, node_key="active", node_type="maintenance_unit",
        sequence_no=2, title="当前单元", status="running", rows_saved=2,
        ingestion_diagnostics_json={"phase": "partial"},
        started_at=datetime.now(timezone.utc),
    )
    session.add(node)
    session.flush()
    value.current_node_id = node.id
    session.commit()
    result = OperationsWorker()._finalize_task_run(
        session, value.id, TaskRunDispatchOutcome(status=status),
    )
    session.refresh(node)
    assert result.status == node.status == status
    assert result.rows_saved == 6
    assert node.rows_saved == 2
    assert node.ingestion_diagnostics_json == {"phase": "partial"}
    assert node.ended_at is not None
