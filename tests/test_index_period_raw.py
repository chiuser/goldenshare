"""Official index period maintenance on isolated PostgreSQL and documented Tushare fields."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.app.runtime.ops_worker_factory import build_operations_worker
from src.foundation.dao.base_dao import BaseDAO
from src.foundation.ingestion import index_period_raw
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.schedule import OpsSchedule
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.queries.task_run_query_service import TaskRunQueryService
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from src.ops.runtime.worker import OperationsWorker
from src.ops.schemas.task_run import TaskRunTimeScope
from src.ops.services.operations_task_run_reconciliation_service import OperationsTaskRunReconciliationService
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext
from src.ops.services.task_run_service import TaskRunCommandService
from tests.wealth_watchlist_postgres_support import isolated_postgres


CODE = "000001.SH"
WEEK_1 = date(2026, 7, 24)
WEEK_2 = date(2026, 7, 31)
WEEK_3 = date(2026, 8, 7)


def source_row(code, day):
    # Field shape from Tushare docs 171/172 and the bounded evidence in LLD §2.1.
    return dict(ts_code=code, trade_date=day.strftime("%Y%m%d"), close=Decimal("100.1234"),
                open=99, high=101, low=98, pre_close=100, change=Decimal("0.1234"),
                pct_chg=Decimal("0.0012"), vol=10000, amount=100000)


def seed_calendar(conn):
    start, end = date(2026, 7, 1), date(2026, 12, 31)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    conn.execute(insert(TradeCalendar), [
        dict(exchange="SSE", trade_date=day, is_open=day.weekday() < 5) for day in days
    ])


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp("index-period-raw")) as engine:
        yield engine


@pytest.fixture
def session(cluster):
    database = "index_raw_" + uuid4().hex
    with cluster.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {database}")
    engine = create_engine(cluster.url.set(database=database))
    try:
        with engine.begin() as conn:
            for schema in ("core_serving", "raw_tushare", "ops"):
                conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
            for model in (TradeCalendar, IndexBasic, IndexSeriesActive, IndexWeeklyServing, IndexMonthlyServing,
                          RawIndexWeeklyBar, RawIndexMonthlyBar, TaskRun, TaskRunNode, TaskRunIssue, OpsSchedule):
                model.__table__.create(conn)
            seed_calendar(conn)
        with Session(engine) as current:
            yield current
    finally:
        engine.dispose()


def enqueue(session, *, point=None, start=WEEK_1, end=WEEK_3, code=None, dataset="index_weekly", schedule_id=None):
    time_input = (
        {"mode": "point", "trade_date": point.isoformat()} if point
        else {"mode": "range", "start_date": start.isoformat(), "end_date": end.isoformat()}
    )
    run = TaskRun(task_type="dataset_action", action="maintain", resource_key=dataset,
                  title=dataset, requested_at=datetime.now(timezone.utc),
                  trigger_source="scheduled" if schedule_id is not None else "manual", schedule_id=schedule_id,
                  time_input_json=time_input, filters_json={"ts_code": code} if code else {})
    session.add(run)
    session.commit()
    return run.id


def execute(session, run_id):
    run = OperationsWorker().run_task_run(session, run_id)
    node = session.get(TaskRunNode, run.current_node_id)
    assert node.status == run.status
    assert node.rows_saved == run.rows_saved
    return run


def source_mock(mocker, provider):
    calls = []

    def call_bounded(*, api_name, params, check, **kwargs):
        check()
        assert kwargs["response_contract"] == "index_period_raw/v1"
        assert len(kwargs["fields"]) == 11
        assert params["limit"] == 1000
        calls.append((api_name, dict(params)))
        day = datetime.strptime(params["trade_date"], "%Y%m%d").date()
        return provider(day, params)

    mocker.patch("src.foundation.ingestion.source_client.create_source_connector",
                 return_value=mocker.Mock(call_bounded=call_bounded))
    return calls


def counts(session, model=RawIndexWeeklyBar):
    with Session(session.get_bind()) as probe:
        return dict(probe.execute(
            select(model.trade_date, func.count()).group_by(model.trade_date)
        ).all())


@pytest.mark.parametrize("fail_after_stage", [False, True])
def test_monthly_raw_commit_queues_serving_with_parent_success_and_can_retry(session, mocker, fail_after_stage):
    day = date(2026, 10, 30)
    # Tushare index_monthly, 000001.SH, 2026-10-30, exact source business fields.
    row = dict(ts_code=CODE, trade_date="20261030", open=3838.9774, high=3864.1181, low=3574.2712,
               close=3599.0166, pre_close=3842.1946, change=-243.178, pct_chg=-0.0633,
               vol=781191473400.0, amount=12647618608842.0)
    calls = source_mock(mocker, lambda *_: [row])
    due = datetime(2026, 11, 2, 11, tzinfo=timezone.utc)
    schedule = OpsSchedule(
        target_type="dataset_action", target_key="index_monthly.maintain", display_name="指数月线 Raw",
        schedule_type="cron", cron_expr="0 19 * * *", calendar_policy="monthly_first_trading_day",
        next_run_at=due,
    )
    session.add(schedule)
    session.commit()
    raw_task, = OperationsScheduleService().enqueue_due_schedules(session, now=due)
    raw_id = raw_task.id
    assert raw_task.time_input_json == {"mode": "point", "trade_date": "2026-10-30"}
    original = TaskRunCommandService.stage_task_run

    def stage(service, pending_session, *, context, **kwargs):
        task = original(service, pending_session, context=context, **kwargs)
        if context.trigger_source == "system":
            with Session(session.get_bind()) as probe:
                raw = probe.get(RawIndexMonthlyBar, (CODE, day))
                parent = probe.scalar(select(TaskRun).where(TaskRun.status == "running"))
                assert raw.close == Decimal("3599.0166")
                assert parent is not None
                assert probe.get(TaskRunNode, parent.current_node_id).status == "running"
                assert probe.get(TaskRun, task.id) is None
            if fail_after_stage and pending_session.get(TaskRun, raw_id).status == "success":
                raise RuntimeError("injected after flushing the child")
        return task

    stage_mock = mocker.patch.object(TaskRunCommandService, "stage_task_run", autospec=True, side_effect=stage)
    result = execute(session, raw_id)
    if fail_after_stage:
        assert result.status == "failed" and result.status_reason_code == "worker_finalize_error"
        assert result.rows_saved == 1 and counts(session, RawIndexMonthlyBar) == {day: 1}
        assert session.scalars(select(TaskRun).where(TaskRun.trigger_source == "system")).all() == []
        mocker.stop(stage_mock)
        retried = TaskRunCommandService().retry_task_run(session, task_run_id=raw_id, requested_by_user_id=1)
        result = execute(session, retried.id)
    assert result.status == "success"
    assert [params["trade_date"] for _, params in calls] == ["20261030"] * (2 if fail_after_stage else 1)
    child = session.scalars(select(TaskRun).where(TaskRun.trigger_source == "system")).one()
    assert child.schedule_id is None and child.status == "queued"
    assert child.time_input_json == {"mode": "point", "trade_date": "2026-10-30"}
    assert child.filters_json == {}
    assert child.request_payload_json["target_key"] == "maintenance.update_index_monthly_serving"

    worker = build_operations_worker(session_factory=lambda: Session(session.get_bind()))
    mocker.patch("src.ops.runtime.index_period_serving_executor.datetime").now.return_value = datetime(
        2026, 11, 2, 16, 15, tzinfo=timezone.utc,
    )
    session.execute(insert(IndexBasic), {"ts_code": CODE, "list_date": date(1991, 7, 15)})
    session.execute(insert(IndexSeriesActive), {
        "resource": "index_period_serving", "ts_code": CODE, "first_seen_date": day,
        "last_seen_date": day, "last_checked_at": datetime.now(timezone.utc),
    })
    session.commit()

    def fail_serving_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO core_serving.index_monthly_serving"):
            raise OperationalError(statement, parameters, RuntimeError("injected Serving write failure"))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", fail_serving_insert)
    try:
        failed_serving = worker.run_task_run(session, child.id)
    finally:
        event.remove(bind, "before_cursor_execute", fail_serving_insert)
    assert failed_serving.status_reason_code == "maintenance_executor_failed"
    assert counts(session, RawIndexMonthlyBar) == {day: 1}
    assert session.scalars(select(IndexMonthlyServing)).all() == []

    retried_serving = TaskRunCommandService().retry_task_run(session, task_run_id=child.id, requested_by_user_id=1)
    published = worker.run_task_run(session, retried_serving.id)
    assert published.status == "success" and published.rows_saved == 1
    serving = session.scalars(select(IndexMonthlyServing)).one()
    assert (serving.trade_date, serving.close, serving.source) == (day, Decimal("3599.0166"), "api")
    assert len(calls) == (2 if fail_after_stage else 1)


@pytest.mark.parametrize(("dataset", "schedule_id", "empty", "status"), [
    ("index_monthly", 1, True, "failed"),
    ("index_monthly", None, False, "success"),
    ("index_weekly", 1, False, "success"),
])
def test_only_successful_scheduled_monthly_raw_can_queue_serving(session, mocker, dataset, schedule_id, empty, status):
    source_mock(mocker, lambda day, _: [] if empty else [source_row(CODE, day)])
    run_id = enqueue(session, point=WEEK_2, dataset=dataset, schedule_id=schedule_id)
    assert execute(session, run_id).status == status
    assert session.scalars(select(TaskRun).where(TaskRun.trigger_source == "system")).all() == []


@pytest.mark.parametrize(("workflow_key", "expected"), [
    ("index_kline_maintenance_pipeline", ["index_daily", "index_weekly", "index_monthly"]),
    ("index_extension_maintenance", ["index_daily", "index_weekly", "index_monthly", "index_daily_basic", "index_weight"]),
])
def test_workflows_run_other_steps_when_range_has_no_period_end(session, mocker, workflow_key, expected):
    session.execute(insert(IndexSeriesActive), [
        {"resource": resource, "ts_code": CODE, "first_seen_date": WEEK_1,
         "last_seen_date": WEEK_1, "last_checked_at": datetime.now(timezone.utc)}
        for resource in ("index_daily_raw", "index_weight")
    ])
    session.commit()
    calls = source_mock(mocker, lambda *_: pytest.fail("a window without a period end must not request Tushare"))
    original = TaskRunDispatcher._run_dataset_action_plan
    ran = []

    def run_step(dispatcher, task_session, step_task, request, plan):
        ran.append(plan.dataset_key)
        if plan.dataset_key in {"index_weekly", "index_monthly"}:
            assert not plan.units
            return original(dispatcher, task_session, step_task, request, plan)
        return 0, 0, 0, {}, {}, "隔离了其他数据集的取数"

    mocker.patch.object(TaskRunDispatcher, "_run_dataset_action_plan", autospec=True, side_effect=run_step)
    run = TaskRun(
        task_type="workflow", action="maintain", title=workflow_key,
        trigger_source="manual", requested_at=datetime.now(timezone.utc),
        time_input_json={"mode": "range", "start_date": "2026-07-27", "end_date": "2026-07-29"},
        request_payload_json={"target_type": "workflow", "target_key": workflow_key},
    )
    session.add(run)
    session.commit()
    result = OperationsWorker().run_task_run(session, run.id)
    nodes = session.scalars(select(TaskRunNode).where(TaskRunNode.task_run_id == run.id)
                            .order_by(TaskRunNode.sequence_no)).all()
    assert [node.resource_key for node in nodes] == expected
    assert calls == []
    if workflow_key == "index_extension_maintenance":
        # Reproduced before stage 3: the existing weight step requires month input.
        assert result.status == "partial_success" and nodes[-1].status == "failed"
        assert session.get(TaskRunIssue, result.primary_issue_id).technical_message == "自然月窗口必须使用 start_month/end_month"
        assert ran == expected[:-1]
        assert all(node.status == "success" for node in nodes[:-1])
    else:
        assert result.status == "success" and ran == expected
        assert all(node.status == "success" for node in nodes)


@pytest.mark.parametrize(("empty_dates", "expected"), [
    ({WEEK_2}, "partial_success"),
    ({WEEK_1, WEEK_2, WEEK_3}, "failed"),
])
def test_code_history_continues_on_empty_and_retries_original_range(session, mocker, empty_dates, expected):
    calls = source_mock(mocker, lambda day, _: [] if day in empty_dates else [source_row(CODE, day)])
    run = execute(session, enqueue(session, code=CODE))
    assert run.status == expected
    issue = session.get(TaskRunIssue, run.primary_issue_id)
    assert issue.code == "index_period_raw.source_missing"
    assert issue.technical_payload_json["missing_periods"] == [
        dict(dataset_key="index_weekly", ts_code=CODE, trade_date=day.isoformat())
        for day in sorted(empty_dates)
    ]
    assert run.unit_done == 3 - len(empty_dates)
    assert run.unit_failed == len(empty_dates)
    assert counts(session) == {day: 1 for day in (WEEK_1, WEEK_2, WEEK_3) if day not in empty_dates}
    first_scope = calls[:]
    empty_dates.clear()
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=run.id, requested_by_user_id=1)
    result = execute(session, retry.id)
    assert result.status == "success"
    assert first_scope == calls[3:]
    assert counts(session) == {WEEK_1: 1, WEEK_2: 1, WEEK_3: 1}


def test_complete_empty_tail_raw_only_and_unseen_rows_preserved(session, mocker):
    session.execute(insert(RawIndexWeeklyBar), dict(ts_code="OLD.SH", trade_date=WEEK_2, close=50))
    session.execute(insert(RawIndexWeeklyBar), dict(
        ts_code=CODE, trade_date=WEEK_2, close=40, api_name="derived_daily",
    ))
    session.execute(insert(IndexWeeklyServing), dict(
        ts_code=CODE, period_start_date=date(2026, 7, 27), trade_date=WEEK_2, close=20, source="derived_daily",
    ))
    session.commit()

    def provide(day, params):
        assert counts(session) == {WEEK_2: 2}
        if params["offset"]:
            return []
        return [source_row(CODE, day)] + [source_row(f"{i:06d}.SZ", day) for i in range(999)]

    calls = source_mock(mocker, provide)
    run = execute(session, enqueue(session, point=WEEK_2))
    assert [params["offset"] for _, params in calls] == [0, 1000]
    assert run.status == "success" and run.rows_saved == 1000 and run.rows_rejected == 0
    assert TaskRunQueryService._period_source_summary(
        session, task_run=run, time_scope=TaskRunTimeScope(
            kind="point", start=WEEK_2.isoformat(), end=WEEK_2.isoformat(), label=WEEK_2.isoformat(),
        ),
    ) is None
    assert counts(session) == {WEEK_2: 1001}
    assert counts(session, RawIndexMonthlyBar) == {}
    session.expire_all()
    stored = session.get(RawIndexWeeklyBar, (CODE, WEEK_2))
    assert (stored.close, stored.api_name) == (Decimal("100.1234"), "index_weekly")
    assert session.scalar(select(IndexWeeklyServing.close)) == 20


@pytest.mark.parametrize(("fault", "code"), [
    ("late_date", "normalize.unit_date_mismatch"),
    ("page_failure", "payload_invalid"),
    ("repeat", "index_period_raw.invalid_page"),
    ("fields", "index_period_raw.source_payload_invalid"),
])
def test_late_page_error_drops_entire_period_but_keeps_prior_commit(session, mocker, fault, code):
    def provide(day, params):
        if day == WEEK_1:
            return [source_row(CODE, day)]
        page = [source_row(f"{i:06d}.SZ", day) for i in range(1000)]
        if params["offset"] == 0:
            return page
        assert counts(session) == {WEEK_1: 1}
        if fault == "repeat":
            return page
        if fault == "page_failure":
            raise ValueError("invalid source page")
        if fault == "fields":
            row = source_row(CODE, day)
            del row["amount"]
            return [row]
        return [source_row(CODE, WEEK_1)]

    calls = source_mock(mocker, provide)
    run = execute(session, enqueue(session))
    assert run.status == "failed" and run.rows_saved == 1
    assert counts(session) == {WEEK_1: 1}
    assert len(calls) == 3
    issue = session.get(TaskRunIssue, run.primary_issue_id)
    assert issue.code == code
    if fault == "late_date":
        assert all(text in issue.operator_message for text in ("指数周线", CODE, "2026-07-24", "2026-07-31"))


def test_filtered_source_rejects_other_code_and_point_empty_reports_date(session, mocker):
    source_mock(mocker, lambda day, _: [source_row("000002.SZ", day)] if day == WEEK_2 else [])
    mismatch = execute(session, enqueue(session, point=WEEK_2, code=CODE))
    issue = session.get(TaskRunIssue, mismatch.primary_issue_id)
    assert issue.code == "index_period_raw.source_payload_invalid"
    assert issue.technical_payload_json["structured_error"]["details"]["expected_ts_code"] == CODE
    session.execute(insert(RawIndexWeeklyBar), dict(ts_code=CODE, trade_date=WEEK_1, close=90))
    session.commit()
    empty = execute(session, enqueue(session, point=WEEK_1))
    issue = session.get(TaskRunIssue, empty.primary_issue_id)
    assert empty.status == "failed" and WEEK_1.isoformat() in issue.operator_message
    assert counts(session) == {WEEK_1: 1}
    assert session.get(RawIndexWeeklyBar, (CODE, WEEK_1)).close == 90


def test_more_than_sixteen_pages_are_written_after_terminal_page(session, mocker):
    def provide(day, params):
        start = params["offset"]
        if start:
            assert counts(session) == {}
        return [source_row(f"{i:06d}.SZ", day) for i in range(start, min(start + 1000, 16001))]

    calls = source_mock(mocker, provide)
    run = execute(session, enqueue(session, point=WEEK_3))
    assert run.status == "success" and run.rows_saved == 16001
    assert len(calls) == 17 and counts(session) == {WEEK_3: 16001}


@pytest.mark.parametrize(("failure", "code"), [
    ("database_error", "write_failed"),
    ("database_deadline", "index_period_raw.write_deadline"),
    ("cancel", "ingestion_canceled"),
])
def test_later_sql_batch_rolls_back_prior_batches_of_same_period(session, mocker, failure, code):
    def provide(day, params):
        if day == WEEK_1:
            return [source_row(CODE, day)]
        return [] if params["offset"] else [source_row(f"{i:06d}.SZ", day) for i in range(1000)]

    source_mock(mocker, provide)
    mocker.patch.object(BaseDAO, "_resolve_batch_size", return_value=500)
    if failure == "database_deadline":
        original = index_period_raw._PeriodControl.__init__

        def short_db_budget(self, **kwargs):
            kwargs["policy"] = replace(kwargs["policy"], db_timeout_seconds=0.5)
            original(self, **kwargs)

        mocker.patch.object(index_period_raw._PeriodControl, "__init__", short_db_budget)
        with session.get_bind().begin() as connection:
            connection.exec_driver_sql("""
                CREATE FUNCTION raw_tushare.delay_second_batch() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.ts_code = '000500.SZ' THEN PERFORM pg_sleep(2); END IF;
                  RETURN NEW;
                END;
                $$;
                CREATE TRIGGER raw_batch_delay BEFORE INSERT ON raw_tushare.index_weekly_bar
                FOR EACH ROW EXECUTE FUNCTION raw_tushare.delay_second_batch();
            """)

    batches = []
    run_id = enqueue(session)

    def on_sql(conn, cursor, sql, params, context, many):
        if not sql.startswith("INSERT INTO raw_tushare.index_weekly_bar"):
            return
        batches.append(sql)
        if len(batches) != 3:
            return
        if failure == "database_error":
            raise RuntimeError("second Raw batch failed")
        if failure == "cancel":
            with Session(session.get_bind()) as cancel:
                task = cancel.get(TaskRun, run_id)
                task.cancel_requested_at = datetime.now(timezone.utc)
                cancel.commit()

    event.listen(session.get_bind(), "before_cursor_execute", on_sql)
    try:
        run = execute(session, run_id)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", on_sql)
    assert run.status == ("canceled" if failure == "cancel" else "failed")
    assert len(batches) == 3 and counts(session) == {WEEK_1: 1}
    assert run.rows_saved == 1
    assert session.get(TaskRunIssue, run.primary_issue_id).code == code


def test_memory_exceeded_during_validation_preserves_preceding_period(session, mocker):
    source_mock(mocker, lambda day, _: [source_row(CODE, day)])
    check = index_period_raw._PeriodControl.check_rows

    def exceed_second_period(self, index):
        if self.unit.trade_date == WEEK_2:
            with patch.object(index_period_raw, "_resident_bytes", return_value=self.policy.memory_limit_bytes):
                check(self, index)
        else:
            check(self, index)

    mocker.patch.object(index_period_raw._PeriodControl, "check_rows", exceed_second_period)
    run = execute(session, enqueue(session))
    assert run.status == "failed" and counts(session) == {WEEK_1: 1}
    issue = session.get(TaskRunIssue, run.primary_issue_id)
    assert issue.code == "index_period_raw.memory_limit"
    assert "采样 3000000000 字节" in issue.operator_message


def test_timeout_during_page_wait(session, mocker):
    clock = [0.0]
    mocker.patch.object(index_period_raw, "monotonic", side_effect=lambda: clock[0])

    def call_bounded(*, check, **kwargs):
        clock[0] += 163
        check()
        raise AssertionError("expected budget failure")

    mocker.patch("src.foundation.ingestion.source_client.create_source_connector",
                 return_value=mocker.Mock(call_bounded=call_bounded))
    run = execute(session, enqueue(session, point=WEEK_2))
    assert run.status == "failed" and counts(session) == {}
    issue = session.get(TaskRunIssue, run.primary_issue_id)
    assert issue.code == "index_period_raw.unit_deadline"
    assert "163 秒" in issue.operator_message


def test_progress_failure_after_commit_preserves_data_and_terminal_counts(session, mocker):
    snapshots = []
    source_mock(mocker, lambda day, _: [source_row(CODE, day)])

    def record_progress(self, **kwargs):
        snapshots.append(kwargs)
        active = kwargs["ingestion_diagnostics"]["runtime"]["paged_unit"]["active"]
        if active is not None:
            sanitized = TaskRunIngestionContext._sanitize_ingestion_diagnostics(kwargs["ingestion_diagnostics"])
            display = TaskRunQueryService._paged_unit_progress(sanitized).active
            assert display.time.point == WEEK_2.isoformat() and display.updated_at
        if kwargs["rows_saved"] == 1:
            assert counts(session, RawIndexMonthlyBar) == {WEEK_2: 1}
            raise RuntimeError("observation store unavailable")

    mocker.patch.object(TaskRunIngestionContext, "update_progress", record_progress)
    run = execute(session, enqueue(session, point=WEEK_2, dataset="index_monthly"))
    assert run.status == "success" and run.rows_saved == 1 and run.unit_done == 1
    assert counts(session, RawIndexMonthlyBar) == {WEEK_2: 1}
    phases = [
        item["ingestion_diagnostics"]["runtime"]["paged_unit"]["active"]["phase"]
        for item in snapshots if item["ingestion_diagnostics"]["runtime"]["paged_unit"]["active"]
    ]
    assert list(dict.fromkeys(phases)) == ["processing_page", "reconciling", "publishing"]
    done = [item["unit_done"] for item in snapshots]
    assert done == sorted(done)


def test_process_exit_preserves_committed_period_then_retry_replays_original_range(session, mocker):
    run_id = enqueue(session, code=CODE)
    process = subprocess.run(
        [sys.executable, "-B", "-c", """
import os, sys
from datetime import datetime
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.foundation.ingestion import source_client
from src.ops.runtime.worker import OperationsWorker
from src.ops.schemas.task_run import TaskRunTimeScope
from tests.test_index_period_raw import CODE, WEEK_2, source_row

def call_bounded(*, params, **kwargs):
    day = datetime.strptime(params['trade_date'], '%Y%m%d').date()
    if day == WEEK_2:
        os._exit(17)
    return [source_row(CODE, day)]

source_client.create_source_connector = lambda _: SimpleNamespace(call_bounded=call_bounded)
with Session(create_engine(sys.argv[1])) as session:
    OperationsWorker().run_task_run(session, int(sys.argv[2]))
""", session.get_bind().url.render_as_string(hide_password=False), str(run_id)],
        capture_output=True, text=True, check=False, timeout=25,
    )
    assert process.returncode == 17, process.stderr
    assert counts(session) == {WEEK_1: 1}
    OperationsTaskRunReconciliationService().reconcile_stale_task_runs(
        session, now=datetime.now(timezone.utc) + timedelta(minutes=11),
    )
    stopped = session.get(TaskRun, run_id)
    assert stopped.status == session.get(TaskRunNode, stopped.current_node_id).status == "failed"
    calls = source_mock(mocker, lambda day, _: [source_row(CODE, day)])
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=run_id, requested_by_user_id=1)
    assert execute(session, retry.id).status == "success"
    assert [params["trade_date"] for _, params in calls] == ["20260724", "20260731", "20260807"]
    assert counts(session) == {WEEK_1: 1, WEEK_2: 1, WEEK_3: 1}


@pytest.mark.parametrize("actually_committed", [True, False])
def test_commit_acknowledgement_loss_checks_persisted_raw(session, mocker, actually_committed):
    source_mock(mocker, lambda day, _: [source_row(CODE, day)])
    commit = Session.commit
    write = DatasetWriter.write

    def mark_business_session(self, **kwargs):
        self.session.info["index_period_raw_commit"] = True
        return write(self, **kwargs)

    def disconnect(self):
        if not self.info.pop("index_period_raw_commit", False):
            return commit(self)
        if actually_committed:
            commit(self)
        raise OperationalError("COMMIT", None, OSError("acknowledgement lost"), connection_invalidated=True)

    mocker.patch.object(DatasetWriter, "write", mark_business_session)
    mocker.patch.object(Session, "commit", disconnect)
    run = execute(session, enqueue(session, point=WEEK_2))
    if actually_committed:
        assert run.status == "success" and counts(session) == {WEEK_2: 1}
    else:
        assert run.status == "failed" and counts(session) == {}
        assert session.get(TaskRunIssue, run.primary_issue_id).code == "index_period_raw.commit_unconfirmed"
