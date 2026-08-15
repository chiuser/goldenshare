from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.foundation.ingestion import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionError, StructuredError
from src.ops.action_catalog import END_DATE_PARAM, START_DATE_PARAM, TRADE_DATE_PARAM, WORKFLOW_DEFINITION_REGISTRY, WorkflowDefinition
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.dataset_date_completeness_schedule import DatasetDateCompletenessSchedule
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.models.ops.task_run import TaskRun
from src.ops.queries.task_run_query_service import TaskRunQueryService
from src.ops.runtime import OperationsScheduler, OperationsWorker, TaskRunDispatchOutcome, TaskRunDispatcher
from src.ops.services.operations_serving_light_refresh_service import ServingLightRefreshResult
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext


class StubDispatcher:
    def __init__(self, outcome: TaskRunDispatchOutcome) -> None:
        self.outcome = outcome
        self.calls: list[int] = []

    def dispatch(self, session, task_run):  # type: ignore[no-untyped-def]
        self.calls.append(task_run.id)
        return self.outcome


def test_scheduler_enqueues_due_once_schedule(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        schedule_type="once",
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].schedule_id == schedule.id
    assert created[0].task_type == "dataset_action"
    assert created[0].resource_key == "stock_basic"
    assert "target_key" not in created[0].request_payload_json
    assert "target_type" not in created[0].request_payload_json
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "paused"
    assert refreshed.next_run_at is None


def test_scheduler_skips_probe_fallback_when_today_probe_task_is_effective(
    db_session,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_daily.maintain",
        schedule_type="cron",
        trigger_mode="schedule_probe_fallback",
        cron_expr="0 20 * * *",
        next_run_at=now,
    )
    task_run_factory(
        resource_key="index_daily",
        trigger_source="probe",
        status="success",
        schedule_id=schedule.id,
        requested_at=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(db_session, now=now)

    assert created == []
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.last_triggered_at is None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > now
    scheduled_task = db_session.scalar(
        select(TaskRun).where(TaskRun.schedule_id == schedule.id, TaskRun.trigger_source == "scheduled")
    )
    assert scheduled_task is None


def test_scheduler_runs_probe_fallback_when_today_probe_task_failed(
    db_session,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_daily.maintain",
        schedule_type="cron",
        trigger_mode="schedule_probe_fallback",
        cron_expr="0 20 * * *",
        next_run_at=now,
    )
    task_run_factory(
        resource_key="index_daily",
        trigger_source="probe",
        status="failed",
        schedule_id=schedule.id,
        requested_at=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(db_session, now=now)

    assert len(created) == 1
    assert created[0].schedule_id == schedule.id
    assert created[0].trigger_source == "scheduled"


def test_scheduler_runs_probe_fallback_when_probe_task_is_previous_day(
    db_session,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_daily.maintain",
        schedule_type="cron",
        trigger_mode="schedule_probe_fallback",
        cron_expr="0 20 * * *",
        next_run_at=now,
    )
    task_run_factory(
        resource_key="index_daily",
        trigger_source="probe",
        status="success",
        schedule_id=schedule.id,
        requested_at=now - timedelta(days=1),
    )

    created = OperationsScheduler().run_once(db_session, now=now)

    assert len(created) == 1
    assert created[0].schedule_id == schedule.id
    assert created[0].trigger_source == "scheduled"


def test_scheduler_enqueues_due_date_completeness_schedule(db_session, trade_calendar_factory) -> None:
    trade_date = date(2026, 6, 25)
    trade_calendar_factory(exchange="SSE", trade_date=trade_date, is_open=True, pretrade_date=date(2026, 6, 24))
    schedule = DatasetDateCompletenessSchedule(
        dataset_key="index_daily",
        display_name="指数日线当日完整性审计",
        status="active",
        window_mode="rolling",
        lookback_count=1,
        lookback_unit="open_day",
        calendar_scope="default_cn_market",
        cron_expr="*/15 17-21 * * *",
        timezone="Asia/Shanghai",
        next_run_at=datetime(2026, 6, 25, 9, 45, tzinfo=timezone.utc),
    )
    db_session.add(schedule)
    db_session.commit()

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert created == []
    audit_run = db_session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "index_daily"))
    assert audit_run is not None
    assert audit_run.run_mode == "scheduled"
    assert audit_run.schedule_id == schedule.id
    assert audit_run.start_date == trade_date
    assert audit_run.end_date == trade_date
    refreshed = db_session.get(DatasetDateCompletenessSchedule, schedule.id)
    assert refreshed is not None
    assert refreshed.last_run_id == audit_run.id
    assert refreshed.next_run_at is not None


def test_scheduler_skips_index_daily_date_completeness_when_today_is_not_open(db_session, trade_calendar_factory) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 24), is_open=True, pretrade_date=date(2026, 6, 23))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 6, 25), is_open=False, pretrade_date=date(2026, 6, 24))
    schedule = DatasetDateCompletenessSchedule(
        dataset_key="index_daily",
        display_name="指数日线当日完整性审计",
        status="active",
        window_mode="rolling",
        lookback_count=1,
        lookback_unit="open_day",
        calendar_scope="default_cn_market",
        cron_expr="*/15 17-21 * * *",
        timezone="Asia/Shanghai",
        next_run_at=datetime(2026, 6, 25, 9, 45, tzinfo=timezone.utc),
    )
    db_session.add(schedule)
    db_session.commit()

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert created == []
    assert db_session.scalar(select(DatasetDateCompletenessRun).where(DatasetDateCompletenessRun.dataset_key == "index_daily")) is None
    refreshed = db_session.get(DatasetDateCompletenessSchedule, schedule.id)
    assert refreshed is not None
    assert refreshed.last_run_id is None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc)


def test_scheduler_dataset_task_uses_target_key_as_single_resource_fact(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="daily.maintain",
        schedule_type="once",
        params_json={
            "dataset_key": "stock_basic",
            "action": "wrong_action",
            "trade_date": "2026-04-24",
        },
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "daily"
    assert task_run.action == "maintain"
    assert task_run.request_payload_json["resource_key"] == "daily"
    assert task_run.request_payload_json["action"] == "maintain"
    assert "dataset_key" not in task_run.request_payload_json


def test_scheduler_reschedules_cron_schedule_after_trigger(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        schedule_type="cron",
        cron_expr="5 * * * *",
        timezone_name="UTC",
        next_run_at=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 10, 5, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "active"
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 3, 30, 11, 5, tzinfo=timezone.utc)


def test_scheduler_monthly_last_day_policy_uses_due_schedule_month_for_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stk_period_bar_month.maintain",
        display_name="股票月线自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="monthly_last_day",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "stk_period_bar_month"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-04-30"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-04-30"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc)


def test_scheduler_monthly_last_trading_day_policy_uses_due_schedule_month_for_task_run(
    db_session,
    ops_schedule_factory,
    trade_calendar_factory,
) -> None:
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 29), is_open=True, pretrade_date=date(2026, 4, 28))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 30), is_open=False, pretrade_date=date(2026, 4, 29))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 28), is_open=True, pretrade_date=date(2026, 5, 27))
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 31), is_open=False, pretrade_date=date(2026, 5, 28))

    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_monthly.maintain",
        display_name="指数月线自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="monthly_last_trading_day",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "index_monthly"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-04-29"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-04-29"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 28, 11, 0, tzinfo=timezone.utc)


def test_scheduler_monthly_window_policy_uses_due_schedule_month_for_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="index_weight.maintain",
        display_name="指数成分权重自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="monthly_window_current_month",
        params_json={"time_input": {"mode": "range"}, "filters": {"index_code": "000300.SH"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "index_weight"
    assert task_run.time_input_json == {
        "mode": "range",
        "start_month": "202604",
        "end_month": "202604",
    }
    assert task_run.filters_json == {"index_code": "000300.SH"}
    assert task_run.request_payload_json["time_input"] == {
        "mode": "range",
        "start_month": "202604",
        "end_month": "202604",
    }
    assert task_run.request_payload_json["filters"] == {"index_code": "000300.SH"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc)


def test_scheduler_trigger_day_single_range_policy_uses_due_schedule_day_for_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="dividend.maintain",
        display_name="分红送股自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="trigger_day_single_range",
        params_json={"time_input": {"mode": "range"}},
        next_run_at=datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "dividend"
    assert task_run.time_input_json == {
        "mode": "range",
        "start_date": "2026-04-30",
        "end_date": "2026-04-30",
    }
    assert task_run.request_payload_json["time_input"] == {
        "mode": "range",
        "start_date": "2026-04-30",
        "end_date": "2026-04-30",
    }
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)


def test_scheduler_trigger_day_point_policy_uses_due_schedule_day_for_news_task_run(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="news.maintain",
        display_name="新闻快讯高频维护",
        schedule_type="cron",
        cron_expr="*/3 * * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="trigger_day_point",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 5, 13, 16, 3, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 13, 16, 3, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "news"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-05-14"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-05-14"}
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == datetime(2026, 5, 13, 16, 6, tzinfo=timezone.utc)


def test_scheduler_trigger_day_point_policy_uses_due_schedule_day_for_fund_share_task_run(
    db_session,
    ops_schedule_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="fund_share.maintain",
        display_name="基金规模自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="trigger_day_point",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "fund_share"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-05-14"}


def test_scheduler_trigger_day_point_policy_uses_ann_date_for_fund_div_task_run(
    db_session,
    ops_schedule_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="fund_div.maintain",
        display_name="基金分红自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="trigger_day_point",
        params_json={"time_input": {"mode": "point"}},
        next_run_at=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.resource_key == "fund_div"
    assert task_run.time_input_json == {
        "mode": "point",
        "ann_date": "2026-05-14",
        "date_field": "ann_date",
    }
    assert task_run.request_payload_json["time_input"] == {
        "mode": "point",
        "ann_date": "2026-05-14",
        "date_field": "ann_date",
    }


def test_scheduler_success_cursor_range_uses_initial_start_then_last_success(
    db_session,
    ops_schedule_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        display_name="业绩快报自动维护",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        timezone_name="Asia/Shanghai",
        calendar_policy="since_last_success_day_range",
        params_json={
            "time_input": {"mode": "range"},
            "schedule_policy_params": {"initial_start_date": "2026-05-10"},
        },
        next_run_at=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    first_batch = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    assert len(first_batch) == 1
    first = first_batch[0]
    assert first.time_input_json == {
        "mode": "range",
        "start_date": "2026-05-10",
        "end_date": "2026-05-13",
    }
    assert "schedule_policy_params" not in first.request_payload_json
    first.status = "success"
    db_session.commit()

    second_batch = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 15, 11, 0, tzinfo=timezone.utc),
    )

    assert len(second_batch) == 1
    second = second_batch[0]
    assert second.schedule_id == schedule.id
    assert second.time_input_json == {
        "mode": "range",
        "start_date": "2026-05-14",
        "end_date": "2026-05-14",
    }


def test_scheduler_success_cursor_ignores_failed_and_other_schedule_windows(
    db_session,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        calendar_policy="since_last_success_day_range",
        params_json={
            "time_input": {"mode": "range"},
            "schedule_policy_params": {"initial_start_date": "2026-05-01"},
        },
        next_run_at=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )
    other_schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        status="paused",
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=schedule.id,
        trigger_source="retry",
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-08"},
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=schedule.id,
        status="failed",
        time_input_json={"mode": "range", "start_date": "2026-05-09", "end_date": "2026-05-12"},
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=schedule.id,
        status="canceled",
        time_input_json={"mode": "range", "start_date": "2026-05-09", "end_date": "2026-05-12"},
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=other_schedule.id,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-12"},
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].time_input_json == {
        "mode": "range",
        "start_date": "2026-05-09",
        "end_date": "2026-05-13",
    }


def test_scheduler_success_cursor_never_runs_before_configured_initial_start(
    db_session,
    ops_schedule_factory,
    task_run_factory,
) -> None:
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        calendar_policy="since_last_success_day_range",
        params_json={
            "time_input": {"mode": "range"},
            "schedule_policy_params": {"initial_start_date": "2026-05-10"},
        },
        next_run_at=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=schedule.id,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-05"},
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    assert created[0].time_input_json == {
        "mode": "range",
        "start_date": "2026-05-10",
        "end_date": "2026-05-13",
    }


def test_scheduler_success_cursor_skips_already_covered_window_without_empty_task_run(
    db_session,
    ops_schedule_factory,
    task_run_factory,
    caplog,
) -> None:
    due_at = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        calendar_policy="since_last_success_day_range",
        params_json={
            "time_input": {"mode": "range"},
            "schedule_policy_params": {"initial_start_date": "2026-05-01"},
        },
        next_run_at=due_at,
    )
    task_run_factory(
        resource_key="express",
        action="maintain",
        schedule_id=schedule.id,
        status="success",
        time_input_json={"mode": "range", "start_date": "2026-05-01", "end_date": "2026-05-13"},
    )

    caplog.set_level("INFO", logger="src.ops.services.operations_schedule_service")
    created = OperationsScheduler().run_once(db_session, now=due_at)

    assert created == []
    tasks = db_session.scalars(select(TaskRun).where(TaskRun.schedule_id == schedule.id)).all()
    assert len(tasks) == 1
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) > due_at
    assert "schedule_window_already_covered" in caplog.text


def test_scheduler_success_cursor_pauses_oversized_window_with_planner_issue(
    db_session,
    ops_schedule_factory,
) -> None:
    due_at = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="express.maintain",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        calendar_policy="since_last_success_day_range",
        params_json={
            "time_input": {"mode": "range"},
            "schedule_policy_params": {"initial_start_date": "2025-01-01"},
        },
        next_run_at=due_at,
    )

    created = OperationsScheduler().run_once(db_session, now=due_at)

    assert len(created) == 1
    failed = created[0]
    assert failed.status == "failed"
    assert failed.status_reason_code == "units_exceeded"
    assert failed.primary_issue_id is not None
    issue = db_session.get(TaskRunIssue, failed.primary_issue_id)
    assert issue is not None
    assert issue.code == "units_exceeded"
    assert issue.source_phase == "planner"
    assert issue.technical_payload_json["structured_error"]["details"]["max_units_per_execution"] == 366
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.status == "paused"
    assert refreshed.next_run_at is None


def test_scheduler_rolls_back_staged_task_and_schedule_advance_together(
    db_session,
    ops_schedule_factory,
    monkeypatch,
) -> None:
    due_at = datetime(2026, 5, 14, 11, 0, tzinfo=timezone.utc)
    schedule = ops_schedule_factory(
        target_type="dataset_action",
        target_key="stock_basic.maintain",
        schedule_type="cron",
        cron_expr="0 19 * * *",
        next_run_at=due_at,
    )

    def fail_next_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("next run calculation failed")

    monkeypatch.setattr(
        "src.ops.services.operations_schedule_service.OperationsScheduleService._resolve_next_run_at",
        fail_next_run,
    )
    with pytest.raises(RuntimeError, match="next run calculation failed"):
        OperationsScheduler().run_once(db_session, now=due_at)
    db_session.rollback()

    assert db_session.scalar(select(TaskRun).where(TaskRun.schedule_id == schedule.id)) is None
    refreshed = db_session.get(type(schedule), schedule.id)
    assert refreshed is not None
    assert refreshed.last_triggered_at is None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at.replace(tzinfo=timezone.utc) == due_at


def test_scheduler_defaults_daily_workflow_to_point_mode_when_schedule_has_no_time_params(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="daily_moneyflow_maintenance",
        schedule_type="once",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.time_input_json == {"mode": "point"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point"}


def test_scheduler_defaults_natural_day_workflow_to_local_calendar_date(db_session, ops_schedule_factory, monkeypatch) -> None:
    workflow = WorkflowDefinition(
        key="test_reference_data_natural_day_workflow",
        display_name="基础数据自然日测试流程",
        description="按自然日维护测试流程。",
        parameters=(TRADE_DATE_PARAM, START_DATE_PARAM, END_DATE_PARAM),
        steps=(),
        schedule_enabled=True,
        manual_enabled=True,
        time_regime="natural_day",
    )
    monkeypatch.setitem(WORKFLOW_DEFINITION_REGISTRY, workflow.key, workflow)
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key=workflow.key,
        schedule_type="once",
        timezone_name="Asia/Shanghai",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-03-31"}
    assert task_run.request_payload_json["time_input"] == {"mode": "point", "trade_date": "2026-03-31"}


def test_scheduler_defaults_reference_data_refresh_workflow_to_snapshot_mode(db_session, ops_schedule_factory) -> None:
    schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="reference_data_refresh",
        schedule_type="once",
        timezone_name="Asia/Shanghai",
        params_json={},
        next_run_at=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    created = OperationsScheduler().run_once(
        db_session,
        now=datetime(2026, 3, 30, 16, 30, tzinfo=timezone.utc),
    )

    assert len(created) == 1
    task_run = created[0]
    assert task_run.schedule_id == schedule.id
    assert task_run.task_type == "workflow"
    assert task_run.resource_key is None
    assert task_run.request_payload_json["target_key"] == "reference_data_refresh"
    assert task_run.time_input_json == {"mode": "none"}
    assert task_run.request_payload_json["time_input"] == {"mode": "none"}


def test_task_run_dispatcher_runs_daily_market_close_workflow_with_bak_basic_step(
    db_session,
    trade_calendar_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    dispatched_dataset_keys: list[str] = []
    resolved_trade_date = date(2026, 4, 24)
    trade_calendar_factory(trade_date=resolved_trade_date, is_open=True)

    def fake_build_plan(self, request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(dataset_key=request.dataset_key, run_profile="point_incremental")

    def fake_run_dataset_action_plan(self, session, task_run, action_request, plan):  # type: ignore[no-untyped-def]
        dispatched_dataset_keys.append(action_request.dataset_key)
        return 1, 1, 0, {}, {}, f"{action_request.dataset_key}:ok"

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetActionResolver.build_plan", fake_build_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_dataset_action_plan", fake_run_dataset_action_plan)

    task_run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="每日收盘后维护",
        status="running",
        time_input_json={"mode": "point"},
        request_payload_json={
            "target_type": "workflow",
            "target_key": "daily_market_close_maintenance",
            "time_input": {"mode": "point"},
            "filters": {},
        },
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)
    nodes = db_session.scalars(
        select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id).order_by(TaskRunNode.sequence_no)
    ).all()

    assert outcome.status == "success"
    assert "bak_basic" in dispatched_dataset_keys
    assert dispatched_dataset_keys[5] == "bak_basic"
    assert len(dispatched_dataset_keys) == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert [node.node_key for node in nodes][:6] == [
        "daily",
        "stk_auction_o",
        "stk_auction_c",
        "adj_factor",
        "daily_basic",
        "bak_basic",
    ]
    assert task_run.unit_total == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert task_run.unit_done == len(WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps)
    assert task_run.progress_percent == 100
    assert task_run.time_input_json == {"mode": "point"}
    assert all(
        node.time_input_json == {"mode": "point", "trade_date": resolved_trade_date.isoformat()}
        for node in nodes
    )


def test_task_run_dispatcher_keeps_point_intent_and_persists_resolved_date_on_dataset_node(
    db_session,
    trade_calendar_factory,
    task_run_factory,
    monkeypatch,
) -> None:
    resolved_trade_date = date(2026, 4, 24)
    trade_calendar_factory(trade_date=resolved_trade_date, is_open=True)

    def fake_build_plan(self, request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            plan_id="daily-point-plan",
            dataset_key=request.dataset_key,
            run_profile="point_incremental",
            planning=SimpleNamespace(unit_count=1),
            units=(),
        )

    def fake_run_dataset_action_plan(self, session, task_run, action_request, plan):  # type: ignore[no-untyped-def]
        return 1, 1, 0, {}, {}, "daily:ok"

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetActionResolver.build_plan", fake_build_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_dataset_action_plan", fake_run_dataset_action_plan)
    task_run = task_run_factory(
        task_type="dataset_action",
        resource_key="daily",
        title="股票日线",
        status="running",
        time_input_json={"mode": "point"},
        request_payload_json={"time_input": {"mode": "point"}, "filters": {}},
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)
    node = db_session.scalar(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id))

    assert outcome.status == "success"
    assert task_run.time_input_json == {"mode": "point"}
    assert node is not None
    assert node.time_input_json == {"mode": "point", "trade_date": resolved_trade_date.isoformat()}


@pytest.mark.parametrize("workflow_key", ["index_extension_maintenance", "index_kline_maintenance_pipeline"])
def test_task_run_dispatcher_runs_index_daily_inside_workflow_without_probe_rule(
    db_session,
    task_run_factory,
    monkeypatch,
    workflow_key: str,
) -> None:
    dispatched_dataset_keys: list[str] = []

    def fake_build_plan(self, request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(dataset_key=request.dataset_key, run_profile="range_rebuild")

    def fake_run_dataset_action_plan(self, session, task_run, action_request, plan):  # type: ignore[no-untyped-def]
        dispatched_dataset_keys.append(action_request.dataset_key)
        return 1, 1, 0, {}, {}, f"{action_request.dataset_key}:ok"

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetActionResolver.build_plan", fake_build_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_dataset_action_plan", fake_run_dataset_action_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_maintenance_action", lambda *args: (0, 0, "maintenance:ok"))

    task_run = task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="指数维护工作流",
        status="running",
        time_input_json={"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-30"},
        request_payload_json={
            "target_type": "workflow",
            "target_key": workflow_key,
            "time_input": {"mode": "range", "start_date": "2026-04-01", "end_date": "2026-04-30"},
            "filters": {},
        },
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)

    assert outcome.status == "success"
    assert dispatched_dataset_keys[0] == "index_daily"
    assert len(dispatched_dataset_keys) == sum(
        step.dataset_key is not None for step in WORKFLOW_DEFINITION_REGISTRY[workflow_key].steps
    )


def test_worker_claims_queued_task_run_and_marks_success(db_session, task_run_factory) -> None:
    task_run = task_run_factory(status="queued", resource_key="daily", title="股票日线")
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success", rows_fetched=10, rows_saved=8, rows_rejected=2))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == task_run.id
    assert result.status == "success"
    assert result.rows_fetched == 10
    assert result.rows_saved == 8
    assert result.rows_rejected == 2
    assert dispatcher.calls == [task_run.id]


def test_worker_preserves_structured_planning_error(db_session, task_run_factory) -> None:
    task_run = task_run_factory(
        status="queued",
        resource_key="fund_portfolio",
        action="maintain",
        title="基金持仓",
        time_input_json={
            "mode": "range",
            "start_date": "2014-01-01",
            "end_date": "2016-03-31",
        },
        filters_json={},
    )

    result = OperationsWorker(dispatcher=TaskRunDispatcher()).run_next(db_session)

    assert result is not None
    assert result.id == task_run.id
    assert result.status == "failed"
    assert result.status_reason_code == "units_exceeded"
    assert result.primary_issue_id is not None
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert issue is not None
    assert issue.code == "units_exceeded"
    assert issue.source_phase == "planner"
    assert issue.operator_message == "本次范围会生成 9 个处理单元，超过单次上限 8 个。请缩小时间范围后重试。"
    assert issue.technical_payload_json["structured_error"]["details"] == {
        "planned_units": 9,
        "max_units_per_execution": 8,
    }
    assert db_session.scalars(select(TaskRunNode).where(TaskRunNode.task_run_id == task_run.id)).all() == []


def test_task_run_dispatcher_preserves_full_source_response_json_on_execution_failure(
    db_session,
    task_run_factory,
    monkeypatch,
) -> None:
    raw_response_json = {
        "code": 50101,
        "msg": "查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
        "data": None,
        "provider_diagnostic": "x" * 40_000,
    }

    def fake_build_plan(self, request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            plan_id="source-error-plan",
            dataset_key=request.dataset_key,
            run_profile="range_rebuild",
            planning=SimpleNamespace(unit_count=1),
            units=(),
        )

    def raise_source_error(self, session, task_run, action_request, plan):  # type: ignore[no-untyped-def]
        raise IngestionError(
            StructuredError(
                error_code="internal_error",
                error_type="internal",
                phase="source_client",
                message="Tushare API error: 查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
                retryable=False,
                unit_id="stk_mins:000001.SZ:5min",
                details={
                    "api_name": "stk_mins",
                    "source_code": 50101,
                    "source_response_json": raw_response_json,
                },
            )
        )

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetActionResolver.build_plan", fake_build_plan)
    monkeypatch.setattr(TaskRunDispatcher, "_run_dataset_action_plan", raise_source_error)
    task_run = task_run_factory(
        status="running",
        resource_key="stock_basic",
        action="maintain",
        title="股票基础信息",
        time_input_json={"mode": "range", "start_date": "2026-08-13", "end_date": "2026-08-13"},
        filters_json={},
    )

    outcome = TaskRunDispatcher().dispatch(db_session, task_run)

    assert outcome.status == "failed"
    assert outcome.issue_id is not None
    issue = db_session.get(TaskRunIssue, outcome.issue_id)
    assert issue is not None
    assert issue.technical_payload_json["structured_error"]["details"] == {
        "api_name": "stk_mins",
        "source_code": 50101,
        "source_response_json": raw_response_json,
    }
    detail = TaskRunQueryService().get_issue_detail(db_session, task_run_id=task_run.id, issue_id=issue.id)
    assert detail.technical_payload["structured_error"]["details"]["source_response_json"] == raw_response_json


def test_worker_does_not_refresh_snapshot_after_workflow_success(db_session, task_run_factory, mocker) -> None:
    refresh = mocker.patch(
        "src.ops.services.operations_dataset_status_snapshot_service.DatasetStatusSnapshotService.refresh_for_target",
        side_effect=AssertionError("ops worker must not refresh dataset snapshots in the main queue path"),
    )
    task_run_factory(
        task_type="workflow",
        resource_key=None,
        title="每日资金流向维护",
        status="queued",
        request_payload_json={
            "target_type": "workflow",
            "target_key": "daily_moneyflow_maintenance",
        },
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.status == "success"
    refresh.assert_not_called()
    snapshot_issues = db_session.scalars(
        select(TaskRunIssue).where(TaskRunIssue.task_run_id == result.id).where(TaskRunIssue.code == "dataset_snapshot_refresh_failed")
    ).all()
    assert snapshot_issues == []


def test_worker_skips_snapshot_refresh_for_maintenance_action(db_session, task_run_factory, mocker) -> None:
    refresh = mocker.patch(
        "src.ops.services.operations_dataset_status_snapshot_service.DatasetStatusSnapshotService.refresh_for_target",
        side_effect=AssertionError("ops worker must not refresh dataset snapshots in the main queue path"),
    )
    task_run_factory(
        task_type="maintenance_action",
        resource_key=None,
        title="刷新数据集市快照",
        status="queued",
        request_payload_json={
            "target_type": "maintenance_action",
            "target_key": "maintenance.rebuild_dm",
        },
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.status == "success"
    refresh.assert_not_called()


def test_worker_cancels_queued_task_run_before_dispatch(db_session, task_run_factory, mocker) -> None:
    refresh = mocker.patch(
        "src.ops.services.operations_dataset_status_snapshot_service.DatasetStatusSnapshotService.refresh_for_target",
        side_effect=AssertionError("canceled queued tasks must not refresh dataset snapshots"),
    )
    requested_at = datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc)
    task_run = task_run_factory(
        status="queued",
        requested_at=requested_at,
        cancel_requested_at=requested_at,
    )
    dispatcher = StubDispatcher(TaskRunDispatchOutcome(status="success"))

    result = OperationsWorker(dispatcher=dispatcher).run_next(db_session)

    assert result is not None
    assert result.id == task_run.id
    assert result.status == "canceled"
    assert result.status_reason_code == "canceled_before_start"
    assert dispatcher.calls == []
    refresh.assert_not_called()


def test_worker_records_issue_when_dispatcher_raises(db_session, task_run_factory, mocker) -> None:
    refresh = mocker.patch(
        "src.ops.services.operations_dataset_status_snapshot_service.DatasetStatusSnapshotService.refresh_for_target",
        side_effect=AssertionError("failed task finalization must not refresh dataset snapshots"),
    )

    class RaisingDispatcher:
        def dispatch(self, session, task_run):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    task_run_factory(status="queued", resource_key="daily", title="股票日线")

    result = OperationsWorker(dispatcher=RaisingDispatcher()).run_next(db_session)  # type: ignore[arg-type]

    assert result is not None
    assert result.status == "failed"
    assert result.primary_issue_id is not None
    issue = db_session.get(TaskRunIssue, result.primary_issue_id)
    assert issue is not None
    assert issue.code == "dispatcher_error"
    assert issue.source_phase == "worker_dispatch"
    assert issue.technical_payload_json["source_phase"] == "worker_dispatch"
    refresh.assert_not_called()


def test_task_run_progress_updates_current_running_node_rows(db_session, task_run_factory, task_run_node_factory) -> None:
    task_run = task_run_factory(status="running", resource_key="limit_list_ths", title="同花顺涨跌停榜单")
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="limit_list_ths:maintain",
        title="维护 同花顺涨跌停榜单",
        status="running",
    )
    task_run.current_node_id = node.id
    db_session.commit()

    TaskRunIngestionContext(db_session).update_progress(
        run_id=task_run.id,
        current=1,
        total=5,
        message="unused structured progress",
        rows_fetched=10514,
        rows_saved=10514,
        rows_rejected=0,
        rows_deduplicated=67,
        ingestion_diagnostics={
            "source": {"pagination": {"unit_samples": [{"unit_id": "fund-div", "page_count": 1}]}},
            "persistence": {"immutable_fact": {"rows_inserted_new": 74, "rows_matched_existing": 0}},
        },
        rejected_reason_counts={},
        current_object={"entity": {"kind": "date", "name": "2026-04-24"}, "time": {}, "attributes": {}},
    )

    db_session.refresh(task_run)
    db_session.refresh(node)
    assert task_run.rows_fetched == 10514
    assert task_run.rows_saved == 10514
    assert node.rows_fetched == 10514
    assert node.rows_saved == 10514
    assert node.rows_rejected == 0
    assert task_run.rows_deduplicated == 67
    assert node.rows_deduplicated == 67
    assert task_run.ingestion_diagnostics_json["persistence"]["immutable_fact"] == {
        "rows_inserted_new": 74,
        "rows_matched_existing": 0,
    }
    assert node.ingestion_diagnostics_json == task_run.ingestion_diagnostics_json


def test_ingestion_diagnostics_are_bounded_to_16_kib() -> None:
    diagnostics = {
        "source": {
            "pagination": {
                "unit_count_with_pagination": 1,
                "total_page_count": 1,
                "total_rows_merged": 74,
                "multi_page_unit_count": 0,
                "max_pages_per_unit": 1,
                "short_page_unit_count": 1,
                "unit_samples": [{"unit_id": "x", "payload": "a" * 20_000}],
            }
        },
        "persistence": {"immutable_fact": {"rows_inserted_new": 74, "rows_matched_existing": 0}},
    }

    sanitized = TaskRunIngestionContext._sanitize_ingestion_diagnostics(diagnostics)

    assert sanitized["truncated"] is True
    assert sanitized["source"]["pagination"]["unit_samples"] == []
    assert sanitized["source"]["pagination"]["total_rows_merged"] == 74
    assert sanitized["persistence"]["immutable_fact"] == {
        "rows_inserted_new": 74,
        "rows_matched_existing": 0,
    }
    assert sanitized["original_bytes"] > 16 * 1024


def test_paged_unit_diagnostics_preserve_active_and_eight_completed_results() -> None:
    completed = [
        {
            "unit_id": f"fund_portfolio:2025{index:02d}30",
            "unit_index": index,
            "time": {"field": "end_date", "point": f"2025-{index:02d}-30"},
            "page_count": 70,
            "retry_count": 0,
            "terminal_page_rows": 730,
            "observed_short_page": True,
            "rows_fetched": 138_730,
            "rows_normalized_before_dedupe": 138_730,
            "rows_staged_unique": 138_730,
            "rows_deduplicated": 0,
            "rows_rejected": 0,
            "rows_inserted_new": 138_730,
            "rows_matched_existing": 0,
            "rows_committed": 138_730,
            "final_scope_count": 138_730,
        }
        for index in range(1, 9)
    ]
    diagnostics = {
        "runtime": {
            "paged_unit": {
                "active": {
                    "unit_id": "fund_portfolio:20251231",
                    "unit_index": 8,
                    "unit_total": 8,
                    "time": {"field": "end_date", "point": "2025-12-31"},
                    "phase": "processing_page",
                    "current_page_number": 28,
                    "completed_page_count": 27,
                    "page_limit": 2_000,
                    "unit_rows_fetched": 54_000,
                    "unit_rows_normalized_before_dedupe": 54_000,
                    "unit_rows_staged_unique": 54_000,
                    "unit_rows_deduplicated": 0,
                    "unit_rows_rejected": 0,
                    "retry_count": 0,
                    "observed_short_page": False,
                    "terminal_page_rows": None,
                },
                "completed": completed,
                "completed_truncated": False,
            }
        }
    }

    sanitized = TaskRunIngestionContext._sanitize_ingestion_diagnostics(diagnostics)

    paged_unit = sanitized["runtime"]["paged_unit"]
    assert paged_unit["active"]["current_page_number"] == 28
    assert len(paged_unit["completed"]) == 8
    assert paged_unit["completed_truncated"] is False
    assert len(json.dumps(sanitized, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


def test_paged_unit_diagnostics_cap_completed_results_and_keep_core_counts() -> None:
    completed = [
        {
            "unit_id": f"unit-{index}",
            "unit_index": index,
            "time": {"field": "end_date", "point": "2025-06-30"},
            "page_count": index,
            "rows_fetched": index * 100,
            "rows_committed": index * 100,
        }
        for index in range(20)
    ]
    diagnostics = {
        "source": {"pagination": {"unit_samples": [{"payload": "x" * 20_000}]}},
        "persistence": {
            "immutable_fact": {"rows_inserted_new": 100, "rows_matched_existing": 20}
        },
        "runtime": {"paged_unit": {"active": None, "completed": completed}},
    }

    sanitized = TaskRunIngestionContext._sanitize_ingestion_diagnostics(diagnostics)

    paged_unit = sanitized["runtime"]["paged_unit"]
    assert len(paged_unit["completed"]) == 16
    assert paged_unit["completed_truncated"] is True
    assert sanitized["persistence"]["immutable_fact"]["rows_inserted_new"] == 100
    assert sanitized["persistence"]["immutable_fact"]["rows_matched_existing"] == 20
    assert len(json.dumps(sanitized, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


def test_task_run_progress_write_failure_is_fail_soft(
    monkeypatch, db_session, task_run_factory
) -> None:  # type: ignore[no-untyped-def]
    task_run = task_run_factory(
        status="running",
        resource_key="fund_portfolio",
        title="公募基金持仓",
        rows_fetched=10,
        rows_saved=10,
    )

    def raise_on_sanitize(_value):  # type: ignore[no-untyped-def]
        raise RuntimeError("ops diagnostics unavailable")

    monkeypatch.setattr(
        TaskRunIngestionContext,
        "_sanitize_ingestion_diagnostics",
        staticmethod(raise_on_sanitize),
    )

    TaskRunIngestionContext(db_session).update_progress(
        run_id=task_run.id,
        current=1,
        total=2,
        message="page progress",
        rows_fetched=2_000,
        rows_saved=10,
        ingestion_diagnostics={"runtime": {"paged_unit": {"active": {}}}},
    )

    db_session.expire_all()
    unchanged = db_session.get(TaskRun, task_run.id)
    assert unchanged is not None
    assert unchanged.rows_fetched == 10
    assert unchanged.rows_saved == 10


def test_task_run_progress_updates_rejected_reason_counts(
    db_session, task_run_factory, task_run_node_factory
) -> None:
    task_run = task_run_factory(
        status="running", resource_key="dc_hot", title="东方财富热榜"
    )
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="dc_hot:maintain",
        title="维护 东方财富热榜",
        status="running",
    )
    task_run.current_node_id = node.id
    db_session.commit()

    TaskRunIngestionContext(db_session).update_progress(
        run_id=task_run.id,
        current=3,
        total=5,
        message="unused structured progress",
        rows_fetched=1530,
        rows_saved=1527,
        rows_rejected=3,
        rejected_reason_counts={"write.duplicate_conflict_key_in_batch:ts_code": 3},
        rejected_reason_samples={
            "write.duplicate_conflict_key_in_batch:ts_code": [
                {"unit_id": "u-dc-hot", "field": "ts_code", "value": "000001.SZ", "row": {"ts_code": "000001.SZ"}}
            ]
        },
        current_object={"entity": {"kind": "date", "name": "2026-04-24"}, "time": {}, "attributes": {}},
    )

    db_session.refresh(task_run)
    db_session.refresh(node)
    assert task_run.rows_rejected == 3
    assert task_run.rejected_reason_counts_json == {"write.duplicate_conflict_key_in_batch:ts_code": 3}
    assert task_run.rejected_reason_samples_json["write.duplicate_conflict_key_in_batch:ts_code"][0]["value"] == "000001.SZ"
    assert node.rejected_reason_counts_json == {"write.duplicate_conflict_key_in_batch:ts_code": 3}
    assert node.rejected_reason_samples_json == task_run.rejected_reason_samples_json


def test_finish_node_preserves_observed_rows_when_final_rows_not_provided(db_session, task_run_factory, task_run_node_factory) -> None:
    task_run = task_run_factory(status="running", resource_key="daily", title="股票日线")
    node = task_run_node_factory(
        task_run_id=task_run.id,
        node_key="daily:maintain",
        title="维护 股票日线",
        status="running",
        rows_fetched=9000,
        rows_saved=8990,
        rows_rejected=10,
        started_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    TaskRunDispatcher._finish_node(node, status="failed")
    db_session.commit()
    db_session.refresh(node)

    assert node.status == "failed"
    assert node.rows_fetched == 9000
    assert node.rows_saved == 8990
    assert node.rows_rejected == 10


def test_task_run_dispatcher_refreshes_daily_serving_light_with_current_service_api(db_session) -> None:
    class StubServingLightRefreshService:
        def __init__(self) -> None:
            self.calls = []

        def refresh_equity_daily_bar(self, session, *, start_date, end_date, ts_code, commit):  # type: ignore[no-untyped-def]
            self.calls.append(
                {
                    "session": session,
                    "start_date": start_date,
                    "end_date": end_date,
                    "ts_code": ts_code,
                    "commit": commit,
                }
            )
            return ServingLightRefreshResult(touched_rows=12)

    light_service = StubServingLightRefreshService()
    dispatcher = TaskRunDispatcher(serving_light_refresh_service=light_service)  # type: ignore[arg-type]

    note = dispatcher._refresh_serving_light_if_needed(
        db_session,
        task_run_id=123,
        resource="daily",
        rows_saved=8,
        trade_date=date(2026, 4, 24),
        ts_code="000001.SZ",
    )

    assert note == "轻量层刷新 12 行"
    assert light_service.calls == [
        {
            "session": db_session,
            "start_date": date(2026, 4, 24),
            "end_date": date(2026, 4, 24),
            "ts_code": "000001.SZ",
            "commit": True,
        }
    ]


def test_task_run_dispatcher_returns_readable_closed_trade_date_skip_message(
    db_session,
    task_run_factory,
    trade_calendar_factory,
) -> None:
    task_run = task_run_factory(status="running", resource_key="daily", title="股票日线")
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 4, 25), is_open=False)
    plan = SimpleNamespace(dataset_key="daily", run_profile="point_incremental")
    action_request = DatasetActionRequest(
        dataset_key="daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 25)),
        filters={},
        trigger_source="manual",
        run_id=task_run.id,
    )

    rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, rejected_reason_samples, summary_message = TaskRunDispatcher()._run_dataset_action_plan(
        db_session,
        task_run,
        action_request,
        plan,
    )

    assert (rows_fetched, rows_saved, rows_rejected) == (0, 0, 0)
    assert rejected_reason_counts == {}
    assert rejected_reason_samples == {}
    assert summary_message == "股票日线：2026-04-25 非交易日，已跳过维护。"


def test_task_run_dispatcher_does_not_skip_natural_day_point_on_closed_trade_date(
    db_session,
    task_run_factory,
    trade_calendar_factory,
    monkeypatch,
) -> None:
    calls: list[DatasetActionRequest] = []

    class StubDatasetMaintainService:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def maintain(self, *, _action_request, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(_action_request)
            return SimpleNamespace(
                rows_fetched=5507,
                rows_written=5507,
                rows_rejected=0,
                rejected_reason_counts={},
                message="units=1",
            )

    monkeypatch.setattr("src.ops.runtime.task_run_dispatcher.DatasetMaintainService", StubDatasetMaintainService)
    task_run = task_run_factory(status="running", resource_key="stk_period_bar_week", title="股票周线行情")
    trade_calendar_factory(exchange="SSE", trade_date=date(2026, 5, 1), is_open=False)
    plan = SimpleNamespace(dataset_key="stk_period_bar_week", run_profile="point_incremental")
    action_request = DatasetActionRequest(
        dataset_key="stk_period_bar_week",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 5, 1)),
        filters={},
        trigger_source="manual",
        run_id=task_run.id,
    )

    rows_fetched, rows_saved, rows_rejected, rejected_reason_counts, rejected_reason_samples, summary_message = TaskRunDispatcher()._run_dataset_action_plan(
        db_session,
        task_run,
        action_request,
        plan,
    )

    assert (rows_fetched, rows_saved, rows_rejected) == (5507, 5507, 0)
    assert rejected_reason_counts == {}
    assert rejected_reason_samples == {}
    assert summary_message == "units=1"
    assert len(calls) == 1
    assert calls[0].time_input.trade_date == date(2026, 5, 1)
