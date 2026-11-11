"""Stage 2 contract through the manual Ops entry and a disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
import subprocess
import sys
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from src.app.exceptions import WebAppError
from src.app.runtime.ops_worker_factory import build_operations_worker
from src.foundation.ingestion.index_period_serving import SHANGHAI, _upsert_bar
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.ops.action_catalog import INDEX_PERIOD_SERVING_EXECUTOR, get_maintenance_action
from src.ops.index_series_active_store_adapter import INDEX_PERIOD_SERVING_RESOURCE
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.queries.manual_action_query_service import ManualActionQueryService
from src.ops.queries.task_run_query_service import TaskRunQueryService
from src.ops.schemas.manual_action import ManualActionTaskRunCreateRequest
from src.ops.services.manual_action_service import ManualActionCommandService
from src.ops.services.review_center_service import ReviewCenterCommandService
from src.ops.services.operations_task_run_reconciliation_service import OperationsTaskRunReconciliationService
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext
from tests.wealth_watchlist_postgres_support import isolated_postgres


WEEK = "maintenance.update_index_weekly_serving"
MONTH = "maintenance.update_index_monthly_serving"
SH, SZ, BSE, A500 = "000001.SH", "399001.SZ", "899050.BJ", "000510.SH"
MON, TUE, WED, FRI = (date(2026, 11, day) for day in (9, 10, 11, 13))
NOW = datetime(2026, 11, 11, 18, tzinfo=SHANGHAI)
A500_START, A500_END = date(2024, 9, 23), date(2024, 9, 30)
BSE_START, BSE_END = date(2022, 11, 21), date(2022, 11, 30)
ALL_CODES = ("000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH",
             "000905.SH", "000852.SH", "899050.BJ", "000510.SH", "000016.SH")


def open_dates(start, end):
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)
            if (start + timedelta(days=offset)).weekday() < 5]


def seed_pool(session, dates, *, resource=INDEX_PERIOD_SERVING_RESOURCE):
    for code, launched in dates.items():
        if session.get(IndexBasic, code) is None:
            session.execute(insert(IndexBasic), dict(ts_code=code, list_date=launched))
        session.execute(insert(IndexSeriesActive), dict(
            resource=resource, ts_code=code, first_seen_date=MON, last_seen_date=MON, last_checked_at=NOW,
        ))
    session.commit()


def seed_daily(session, code, days):
    session.execute(insert(RawIndexDaily), [
        dict(ts_code=code, trade_date=day, open=100, high=106, low=98,
             close=102, pre_close=100, vol=7, amount=250)
        for day in days
    ])
    session.commit()


def seed_formal(session, model, code, day, *, api_name, close=105):
    session.execute(insert(model), dict(
        ts_code=code, trade_date=day, api_name=api_name, open=100, high=106, low=98,
        close=close, pre_close=0, change=5, pct_chg=0, vol=700, amount=250000,
    ))
    session.commit()


def enqueue(session, action, day, code=None):
    return ManualActionCommandService().create_task_run_for_action(
        session, user=SimpleNamespace(id=1), action_key=action,
        body=ManualActionTaskRunCreateRequest(
            time_input={"mode": "point", "trade_date": day.isoformat()},
            filters={"ts_code": code} if code else {},
        ),
    )


def run(session, worker, action, day, code=None):
    result = worker.run_task_run(session, enqueue(session, action, day, code))
    node = session.get(TaskRunNode, result.current_node_id)
    assert node.status == result.status and node.rows_saved == result.rows_saved
    return result


def diagnostic(session, result):
    return TaskRunQueryService().get_issue_detail(
        session, task_run_id=result.id, issue_id=result.primary_issue_id,
    ).technical_payload


def records(session, model):
    return session.scalars(select(model).order_by(model.ts_code, model.period_start_date)).all()


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp("index-period-serving")) as engine:
        yield engine


@pytest.fixture
def env(cluster, mocker):
    database = "index_serving_" + uuid4().hex
    with cluster.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {database}")
    engine = create_engine(cluster.url.set(database=database))

    def fixed_time(zone):
        return NOW.astimezone(zone)

    clock = mocker.patch("src.ops.runtime.index_period_serving_executor.datetime")
    clock.now.side_effect = fixed_time
    try:
        with engine.begin() as conn:
            for schema in ("core_serving", "raw_tushare", "ops"):
                conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
            for model in (IndexBasic, TradeCalendar, IndexSeriesActive, RawIndexDaily, RawIndexWeeklyBar,
                          RawIndexMonthlyBar, IndexWeeklyServing, IndexMonthlyServing,
                          TaskRun, TaskRunIssue, TaskRunNode):
                model.__table__.create(conn)
            bounds = [(date(2022, 11, 1), BSE_END), (date(2024, 9, 1), A500_END),
                      (date(2026, 9, 28), date(2026, 10, 4)), (date(2026, 11, 1), date(2026, 11, 30))]
            holidays = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 11, 16)}
            conn.execute(insert(TradeCalendar), [
                dict(exchange="SSE", trade_date=day, is_open=day.weekday() < 5 and day not in holidays)
                for start, end in bounds for day in (start + timedelta(days=offset)
                                                     for offset in range((end - start).days + 1))
            ])
        factory = sessionmaker(bind=engine)
        with factory() as session:
            yield session, build_operations_worker(session_factory=factory), clock
    finally:
        engine.dispose()


@pytest.mark.parametrize(("action", "target"), [(WEEK, "index_weekly_serving"), (MONTH, "index_monthly_serving")])
def test_manual_action_has_one_trade_date_optional_code_and_one_target(action, target):
    route = ManualActionQueryService().get_action_route(action)
    assert [(mode.mode, mode.control) for mode in route.time_form.modes] == [("point", "trade_date")]
    assert [(param.key, param.required) for param in route.filters] == [("ts_code", False)]
    definition = get_maintenance_action(action)
    assert definition.target_tables == (f"core_serving.{target}",)
    assert definition.manual_enabled and definition.retry_enabled and definition.schedule_enabled


def enqueue_scheduled(session, action, day):
    return TaskRunCommandService().create_task_run(session, context=TaskRunCreateContext(
        task_type="maintenance_action", resource_key=None, action="maintain",
        time_input={"mode": "point", "trade_date": day.isoformat()}, filters={},
        request_payload={"target_type": "maintenance_action", "target_key": action},
        trigger_source="scheduled", schedule_id=1, requested_by_user_id=None,
    ))


def test_scheduled_retry_can_run_the_same_evening(env):
    session, worker, clock = env
    clock.now.return_value = datetime(2026, 11, 9, 22, tzinfo=SHANGHAI)
    clock.now.side_effect = None
    seed_pool(session, {SH: MON})
    initial = worker.run_task_run(session, enqueue_scheduled(session, WEEK, MON).id)
    assert initial.status == "failed" and initial.rows_saved == 0
    seed_daily(session, SH, [MON])
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=initial.id, requested_by_user_id=1)
    result = worker.run_task_run(session, retry.id)
    assert result.status == "success" and result.rows_saved == 1
    assert records(session, IndexWeeklyServing)[0].trade_date == MON


def test_scheduled_serving_stops_after_midnight_and_only_manual_can_fill_original_day(env, mocker):
    session, worker, clock = env
    current = datetime(2026, 11, 9, 23, 59, tzinfo=SHANGHAI)
    clock.now.side_effect = lambda zone: current.astimezone(zone)
    seed_pool(session, {SH: MON, SZ: MON})
    for code in (SH, SZ):
        seed_daily(session, code, [MON])

    executor = worker.dispatcher.maintenance_executors[INDEX_PERIOD_SERVING_EXECUTOR]
    original = executor.execute_code

    def finish_first_code(*args):
        nonlocal current
        result = original(*args)
        current = datetime(2026, 11, 10, 0, tzinfo=SHANGHAI)
        return result

    run_code = mocker.patch.object(executor, "execute_code", side_effect=finish_first_code)
    scheduled = worker.run_task_run(session, enqueue_scheduled(session, WEEK, MON).id)
    assert scheduled.status == "failed" and scheduled.rows_saved == 1
    assert scheduled.status_reason_code == "index_period_serving.schedule_expired"
    assert diagnostic(session, scheduled)["trade_date"] == "2026-11-09"
    assert run_code.call_count == 1
    assert session.get(TaskRunNode, scheduled.current_node_id).status == "failed"

    late_month = worker.run_task_run(session, enqueue_scheduled(session, MONTH, MON).id)
    assert late_month.status_reason_code == "index_period_serving.schedule_expired"
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=scheduled.id, requested_by_user_id=1)
    assert worker.run_task_run(session, retry.id).status_reason_code == "index_period_serving.schedule_expired"
    assert run_code.call_count == 1
    assert records(session, IndexMonthlyServing) == []
    assert len(records(session, IndexWeeklyServing)) == 1
    assert run(session, worker, WEEK, MON).status == "success"
    assert {row.trade_date for row in records(session, IndexWeeklyServing)} == {MON}
    assert len(records(session, IndexWeeklyServing)) == 2


def test_two_frequencies_share_fixed_pool_and_reject_edits(env):
    session, worker, _ = env
    seed_pool(session, {SH: date(1991, 7, 15)}, resource="index_daily")
    for action in (WEEK, MONTH):
        failed = run(session, worker, action, MON)
        assert failed.status_reason_code == "index_period_serving.pool_empty"
        assert "激活池未初始化" in diagnostic(session, failed)["failures"][0]["message"]
    seed_pool(session, {SZ: MON})
    commands = ReviewCenterCommandService()
    for command, code in ((commands.add_active_index, SH), (commands.remove_active_index, SZ)):
        with pytest.raises(WebAppError, match="首期禁止增删"):
            command(session, resource=INDEX_PERIOD_SERVING_RESOURCE, ts_code=code)
    for action, model in ((WEEK, IndexWeeklyServing), (MONTH, IndexMonthlyServing)):
        invalid = run(session, worker, action, MON, SH)
        assert invalid.status_reason_code == "index_period_serving.code_outside_pool"
        seed_model = RawIndexWeeklyBar if action == WEEK else RawIndexMonthlyBar
        anchor = FRI if action == WEEK else date(2026, 11, 30)
        seed_formal(session, seed_model, SZ, anchor, api_name="index_weekly" if action == WEEK else "index_monthly")
        assert run(session, worker, action, MON).rows_saved == 1
        assert [row.ts_code for row in records(session, model)] == [SZ]
    assert session.get(IndexSeriesActive, ("index_daily", SH)) is not None


def test_first_day_gaps_diagnostics_all_codes_original_retry_and_no_regression(env):
    session, worker, _ = env
    seed_pool(session, {SH: MON, A500: MON, BSE: MON})
    seed_daily(session, SH, [MON, WED])
    seed_daily(session, A500, [MON, TUE, WED])
    seed_daily(session, BSE, [MON, TUE, WED])

    # SH creates its first weekly bar; A500 remains without a prior bar.
    first = run(session, worker, WEEK, MON, SH)
    assert first.status == "success"
    assert run(session, worker, WEEK, MON, SH).rows_saved == 1
    assert run(session, worker, WEEK, MON, BSE).rows_saved == 1
    assert run(session, worker, WEEK, TUE, BSE).rows_saved == 1

    missing = run(session, worker, WEEK, TUE, SH)
    assert diagnostic(session, missing)["failures"][0]["details"]["missing_dates"] == [TUE.isoformat()]
    result = run(session, worker, WEEK, WED)
    assert (result.status, result.unit_done, result.unit_failed, result.rows_saved) == ("failed", 1, 2, 1)
    detail = diagnostic(session, result)
    assert detail["rows_saved"] == 1
    assert [(item["details"]["ts_code"], item["details"]["expected_trade_date"],
             item["details"]["actual_trade_date"]) for item in detail["failures"]] == [
        (SH, TUE.isoformat(), MON.isoformat()), (A500, TUE.isoformat(), None),
    ]
    assert [(row.ts_code, row.trade_date) for row in records(session, IndexWeeklyServing)] == [(SH, MON), (BSE, WED)]
    assert records(session, IndexMonthlyServing) == []

    seed_daily(session, SH, [TUE])
    for action, day, code in ((WEEK, TUE, SH), (WEEK, MON, A500), (WEEK, TUE, A500)):
        assert run(session, worker, action, day, code).status == "success"
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=result.id, requested_by_user_id=1)
    assert retry.time_input_json == result.time_input_json and retry.filters_json == result.filters_json
    result = worker.run_task_run(session, retry.id)
    assert (result.status, result.rows_saved) == ("success", 3)
    earlier = run(session, worker, WEEK, TUE, SH)
    assert (earlier.status, earlier.rows_saved) == ("success", 0)
    assert all(row.trade_date == WED for row in records(session, IndexWeeklyServing))


@pytest.mark.parametrize(("target", "now", "reason"), [
    (WED, datetime(2026, 11, 11, 14, 59, tzinfo=SHANGHAI), "尚未收盘"),
    (FRI, NOW, "尚未收盘"),
    (date(2026, 11, 14), datetime(2026, 11, 14, 17, tzinfo=SHANGHAI), "不是交易日"),
    (MON, datetime(2026, 11, 18, 17, tzinfo=SHANGHAI), "实际最后一个交易日"),
    (date(2026, 10, 9), NOW, "交易日历不完整"),
])
def test_invalid_target_leaves_serving_untouched(env, target, now, reason):
    session, worker, clock = env
    clock.now.side_effect = lambda zone: now.astimezone(zone)
    seed_pool(session, {SH: date(1991, 7, 15)})
    result = run(session, worker, WEEK, target)
    assert result.status == "failed" and records(session, IndexWeeklyServing) == []
    assert reason in diagnostic(session, result)["failures"][0]["message"]


def test_complete_short_week_uses_real_last_open_day(env):
    session, worker, _ = env
    start, end = date(2026, 9, 28), date(2026, 9, 30)
    seed_pool(session, {SH: date(1991, 7, 15)})
    seed_daily(session, SH, open_dates(start, end))
    assert run(session, worker, WEEK, end).status == "success"
    row = records(session, IndexWeeklyServing)[0]
    assert (row.period_start_date, row.trade_date, row.vol, row.amount) == (start, end, 2100, 750000)


def test_launch_windows_north_exchange_and_a500_manual_raw_then_formal_replacement(env):
    session, worker, _ = env
    seed_pool(session, {A500: A500_START, BSE: BSE_START, SH: date(1991, 7, 15)})
    for code, start, end in ((A500, A500_START, A500_END), (BSE, BSE_START, BSE_END)):
        seed_daily(session, code, [start - timedelta(days=4), *open_dates(start, end)])
    seed_formal(session, RawIndexMonthlyBar, A500, A500_END, api_name="derived_daily", close=999)
    for code, start, end, period_start, num_days in (
        (A500, A500_START, A500_END, date(2024, 9, 2), 6),
        (BSE, BSE_START, BSE_END, date(2022, 11, 1), 8),
    ):
        initial = run(session, worker, MONTH, end, code)
        assert (initial.status, initial.rows_saved) == ("success", 1)
        row = session.scalar(select(IndexMonthlyServing).where(IndexMonthlyServing.ts_code == code))
        assert (row.period_start_date, row.trade_date, row.close, row.source) == (period_start, end, 102, "derived_daily")
        assert (row.pre_close, row.pct_chg, row.vol, row.amount) == (100, Decimal("0.0200"), 700 * num_days, 250000 * num_days)
    # Formal values remain authoritative, including zero pre_close and pct_chg.
    seed_formal(session, RawIndexMonthlyBar, SH, A500_END, api_name="index_monthly")
    session.execute(RawIndexMonthlyBar.__table__.update().where(RawIndexMonthlyBar.ts_code == A500)
                    .values(api_name="index_monthly", close=107))
    session.commit()
    assert run(session, worker, MONTH, A500_END).rows_saved == 2  # BSE lacks this period's daily data.
    assert session.get(IndexMonthlyServing, (A500, A500_END)).close == 107
    row = session.get(IndexMonthlyServing, (SH, A500_END))
    assert (row.source, row.pre_close, row.pct_chg, row.vol, row.amount) == ("api", 0, 0, 700, 250000)
    assert session.get(RawIndexMonthlyBar, (A500, A500_END)).api_name == "index_monthly"


def test_formal_week_replaces_partial_bar_even_when_daily_data_is_incomplete(env):
    session, worker, clock = env
    seed_pool(session, {SH: MON})
    seed_daily(session, SH, [MON])
    assert run(session, worker, WEEK, MON).rows_saved == 1
    seed_formal(session, RawIndexWeeklyBar, SH, FRI, api_name="index_weekly")
    clock.now.side_effect = lambda zone: datetime(2026, 11, 13, 18, tzinfo=SHANGHAI).astimezone(zone)
    assert run(session, worker, WEEK, FRI).rows_saved == 1
    row = records(session, IndexWeeklyServing)[0]
    assert (row.trade_date, row.period_start_date, row.close, row.source) == (FRI, MON, 105, "api")
    # With a source outage, the official Serving bar remains authoritative.
    session.execute(RawIndexWeeklyBar.__table__.update().where(RawIndexWeeklyBar.ts_code == SH)
                    .values(trade_date=date(2026, 11, 6)))
    session.commit()
    assert run(session, worker, WEEK, MON).rows_saved == 0
    assert records(session, IndexWeeklyServing)[0].source == "api"


def test_cancel_after_first_commit_and_retry_original_scope(env):
    session, worker, _ = env
    seed_pool(session, {SH: MON, A500: MON, BSE: MON})
    for code in (SH, A500, BSE):
        seed_daily(session, code, [MON])
    run_id = enqueue(session, WEEK, MON)
    executor = worker.dispatcher.maintenance_executors[INDEX_PERIOD_SERVING_EXECUTOR]
    original = executor.execute_code

    def cancel_after_commit(period, code, list_date):
        result = original(period, code, list_date)
        with Session(session.get_bind()) as cancel_session:
            TaskRunCommandService().request_cancel(cancel_session, task_run_id=run_id, requested_by_user_id=1)
        return result

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(executor, "execute_code", cancel_after_commit)
        canceled = worker.run_task_run(session, run_id)
    node = session.get(TaskRunNode, canceled.current_node_id)
    assert (canceled.status, node.status, canceled.rows_saved, node.rows_saved) == ("canceled", "canceled", 1, 1)
    assert [row.ts_code for row in records(session, IndexWeeklyServing)] == [SH]
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=run_id, requested_by_user_id=1)
    assert worker.run_task_run(session, retry.id).rows_saved == 3
    assert len(records(session, IndexWeeklyServing)) == 3


def test_full_pool_and_observation_write_failure_still_commit_each_code(env):
    session, worker, _ = env
    seed_pool(session, {code: MON for code in ALL_CODES})
    for code in ALL_CODES:
        seed_daily(session, code, [MON])
    touched = []
    failed_observations = []

    def observe(_, __, sql, *args):
        if "raw_tushare." in sql and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            touched.append(sql)

    def fail_progress_flush(progress_session, *_):
        for task in progress_session.dirty:
            if isinstance(task, TaskRun) and task.current_object_json.get("entity"):
                failed_observations.append(task.current_object_json["entity"]["code"])
                raise RuntimeError("simulated progress write failure")

    event.listen(session.get_bind(), "before_cursor_execute", observe)
    event.listen(Session, "before_flush", fail_progress_flush)
    try:
        result = run(session, worker, WEEK, MON)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", observe)
        event.remove(Session, "before_flush", fail_progress_flush)
    assert touched == []
    assert failed_observations == sorted(ALL_CODES)
    assert (result.status, result.unit_done, result.rows_saved) == ("success", 10, 10)
    assert len(records(session, IndexWeeklyServing)) == 10
    assert session.scalar(select(func.count()).select_from(RawIndexDaily)) == 10


def test_running_progress_shows_current_index_and_date_with_committed_count(env):
    session, worker, _ = env
    seed_pool(session, {SH: MON, BSE: MON})
    for code in (SH, BSE):
        seed_daily(session, code, [MON])
    run_id = enqueue(session, WEEK, MON)
    executor = worker.dispatcher.maintenance_executors[INDEX_PERIOD_SERVING_EXECUTOR]
    original = executor.execute_code
    snapshots = []

    def check_progress(period, code, list_date):
        with Session(session.get_bind()) as probe:
            task = probe.get(TaskRun, run_id)
            display = TaskRunQueryService._display_current_object(task.current_object_json, status=task.status)
            assert display.title == f"正在处理：{code}"
            assert any(field.value == MON.isoformat() for field in display.fields)
            snapshots.append((task.unit_done, task.unit_total, task.progress_percent, task.rows_saved))
        return original(period, code, list_date)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(executor, "execute_code", check_progress)
        result = worker.run_task_run(session, run_id)
    assert snapshots == [(0, 2, 0, 0), (1, 2, 50, 1)]
    assert (result.status, result.unit_done, result.rows_saved) == ("success", 2, 2)


def test_periods_before_release_stay_empty_and_pool_size_is_bounded(env):
    session, worker, _ = env
    seed_pool(session, {SH: MON})
    old_end = date(2026, 9, 30)
    seed_formal(session, RawIndexWeeklyBar, SH, old_end, api_name="index_weekly")
    skipped = run(session, worker, WEEK, old_end, SH)
    assert (skipped.status, skipped.rows_saved) == ("success", 0)
    assert records(session, IndexWeeklyServing) == []
    seed_pool(session, {code: MON for code in (*ALL_CODES, "000002.SH") if code != SH})
    blocked = run(session, worker, WEEK, MON)
    assert blocked.status_reason_code == "index_period_serving.pool_size"
    assert records(session, IndexWeeklyServing) == []


def test_worker_exit_after_commit_keeps_rows_and_original_scope_can_be_retried(env):
    session, worker, _ = env
    seed_pool(session, {A500: A500_START, SH: A500_START, BSE: A500_START})
    for code in (A500, SH, BSE):
        seed_daily(session, code, open_dates(A500_START, A500_END))
    run_id = enqueue(session, MONTH, A500_END)
    subprocess_result = subprocess.run(
        [sys.executable, "-B", "-c", """
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.app.runtime.ops_worker_factory import build_operations_worker
from src.ops.action_catalog import INDEX_PERIOD_SERVING_EXECUTOR

factory = sessionmaker(bind=create_engine(sys.argv[1]))
worker = build_operations_worker(session_factory=factory)
executor = worker.dispatcher.maintenance_executors[INDEX_PERIOD_SERVING_EXECUTOR]
original = executor.execute_code

def exit_after_commit(period, code, list_date):
    original(period, code, list_date)
    os._exit(17)

executor.execute_code = exit_after_commit
with factory() as session:
    worker.run_task_run(session, int(sys.argv[2]))
""", session.get_bind().url.render_as_string(hide_password=False), str(run_id)],
        capture_output=True, text=True, timeout=25, check=False,
    )
    assert subprocess_result.returncode == 17, subprocess_result.stderr
    assert [row.ts_code for row in records(session, IndexMonthlyServing)] == [SH]
    OperationsTaskRunReconciliationService().reconcile_stale_task_runs(
        session, now=datetime.now(SHANGHAI) + timedelta(minutes=11),
    )
    interrupted = session.get(TaskRun, run_id)
    assert interrupted.status == session.get(TaskRunNode, interrupted.current_node_id).status == "failed"
    retry = TaskRunCommandService().retry_task_run(session, task_run_id=run_id, requested_by_user_id=1)
    assert worker.run_task_run(session, retry.id).rows_saved == 3
    assert len(records(session, IndexMonthlyServing)) == 3


@pytest.mark.parametrize(("winning_source", "winning_date"), [("api", FRI), ("derived_daily", WED)])
def test_conflict_preserves_official_or_later_bar_from_another_transaction(env, winning_source, winning_date):
    session, _, _ = env
    engine = session.get_bind()
    about_to_upsert = Event()

    def update_with_old_derived():
        with Session(engine) as other:
            def before_write(*_):
                about_to_upsert.set()

            event.listen(other.connection(), "before_cursor_execute", before_write, once=True)
            result = _upsert_bar(
                other, IndexWeeklyServing, ts_code=SH, period_start=MON,
                trade_date=winning_date if winning_source == "api" else TUE,
                source="derived_daily", values={"close": Decimal("90")},
            )
            other.commit()
            return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(engine) as winning:
            assert _upsert_bar(
                winning, IndexWeeklyServing, ts_code=SH, period_start=MON, trade_date=winning_date,
                source=winning_source, values={"close": Decimal("105")},
            ) == 1
            pending = pool.submit(update_with_old_derived)
            assert about_to_upsert.wait(timeout=5)
            winning.commit()
        assert pending.result(timeout=5) == 0
    row, = records(session, IndexWeeklyServing)
    assert (row.trade_date, row.source, row.close) == (winning_date, winning_source, 105)
