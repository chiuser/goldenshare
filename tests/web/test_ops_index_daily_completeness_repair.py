from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.ops.models.ops.dataset_date_completeness_run import DatasetDateCompletenessRun
from src.ops.models.ops.index_series_active import IndexSeriesActive
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.date_completeness_audit_service import DateCompletenessAuditWorker
from src.ops.services.date_completeness_run_service import DateCompletenessRunCommandService
from src.ops.services.index_daily_completeness_repair_service import (
    IndexDailyCompletenessRepairService,
)
from src.ops.services.index_daily_reconciliation_policy import (
    INDEX_DAILY_GAP_REPAIR_RUN_SCOPE,
    INDEX_DAILY_REPAIR_BATCH_SIZE,
    INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON,
    INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING,
    INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL,
)


def _seed_open_day(db_session: Session, trade_date: date) -> None:
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=trade_date,
            is_open=True,
            pretrade_date=trade_date,
        )
    )


def _seed_active_indexes(db_session: Session, codes: list[str], *, trade_date: date) -> None:
    checked_at = datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc)
    db_session.add_all(
        [
            IndexSeriesActive(
                resource="index_daily",
                ts_code=code,
                first_seen_date=trade_date,
                last_seen_date=trade_date,
                last_checked_at=checked_at,
            )
            for code in codes
        ]
    )


def _seed_serving_rows(db_session: Session, codes: list[str], *, trade_date: date) -> None:
    db_session.add_all([IndexDailyServing(ts_code=code, trade_date=trade_date) for code in codes])


def _seed_raw_rows(db_session: Session, codes: list[str], *, trade_date: date) -> None:
    db_session.add_all(
        [
            RawIndexDaily(
                ts_code=code,
                trade_date=trade_date,
                api_name="index_daily",
                fetched_at=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
            )
            for code in codes
        ]
    )


def _create_source_run(
    db_session: Session,
    *,
    trade_date: date,
    result_status: str = "failed",
    requested_at: datetime | None = None,
    run_mode: str = "scheduled",
    requested_by_user_id: int | None = None,
    schedule_id: int | None = None,
) -> DatasetDateCompletenessRun:
    run = DatasetDateCompletenessRun(
        dataset_key="index_daily",
        display_name="指数日线行情",
        target_table="core_serving.index_daily_serving",
        run_mode=run_mode,
        run_status="succeeded",
        result_status=result_status,
        start_date=trade_date,
        end_date=trade_date,
        date_axis="trade_open_day",
        bucket_rule="every_open_day",
        window_mode="point_or_range",
        input_shape="trade_date_or_start_end",
        observed_field="trade_date",
        bucket_window_rule="none",
        bucket_applicability_rule="always",
        row_identity_filters_json={},
        audit_scope="date_subject_matrix",
        subject_kind="index",
        expected_cell_count=1 if result_status == "failed" else 0,
        missing_cell_count=1 if result_status == "failed" else 0,
        affected_bucket_count=1 if result_status == "failed" else 0,
        affected_subject_count=1 if result_status == "failed" else 0,
        current_stage="completed",
        requested_by_user_id=requested_by_user_id,
        schedule_id=schedule_id,
        requested_at=requested_at or datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def _codes(count: int) -> list[str]:
    return [f"{index:06d}.SH" for index in range(1, count + 1)]


def test_index_daily_repair_creates_single_task_run_for_small_gap(db_session) -> None:
    trade_date = date(2026, 4, 24)
    active_codes = ["000001.SH", "399001.SZ", "399300.SZ"]
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, active_codes, trade_date=trade_date)
    _seed_serving_rows(db_session, ["000001.SH"], trade_date=trade_date)
    _seed_raw_rows(db_session, active_codes, trade_date=trade_date)
    source_run = _create_source_run(db_session, trade_date=trade_date)

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    task_run = task_runs[0]
    assert task_run.task_type == "dataset_action"
    assert task_run.resource_key == "index_daily"
    assert task_run.action == "maintain"
    assert task_run.status == "queued"
    assert task_run.trigger_source == "system"
    assert task_run.time_input_json == {"mode": "point", "trade_date": "2026-04-24"}
    assert task_run.filters_json == {"ts_code": "399001.SZ,399300.SZ"}
    assert task_run.request_payload_json["run_scope"] == INDEX_DAILY_GAP_REPAIR_RUN_SCOPE
    assert task_run.request_payload_json["repair_slot"] == INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL
    assert task_run.request_payload_json["source_date_completeness_run_id"] == source_run.id
    assert task_run.request_payload_json["repair_trade_date"] == "2026-04-24"
    assert task_run.request_payload_json["missing_code_count"] == 2
    assert task_run.request_payload_json["batch_index"] == 1
    assert task_run.request_payload_json["batch_size"] == 2


def test_index_daily_repair_batches_missing_codes_by_one_hundred(db_session) -> None:
    trade_date = date(2026, 4, 24)
    active_codes = _codes(250)
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, active_codes, trade_date=trade_date)
    _seed_raw_rows(db_session, active_codes, trade_date=trade_date)
    source_run = _create_source_run(db_session, trade_date=trade_date)

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 3
    assert [len(run.filters_json["ts_code"].split(",")) for run in task_runs] == [100, 100, 50]
    assert [run.request_payload_json["batch_index"] for run in task_runs] == [1, 2, 3]
    assert [run.request_payload_json["batch_size"] for run in task_runs] == [100, 100, 50]
    assert {run.request_payload_json["missing_code_count"] for run in task_runs} == {250}


def test_index_daily_repair_caps_task_runs_per_round(db_session) -> None:
    trade_date = date(2026, 4, 24)
    active_codes = _codes(2500)
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, active_codes, trade_date=trade_date)
    _seed_raw_rows(db_session, active_codes, trade_date=trade_date)
    source_run = _create_source_run(db_session, trade_date=trade_date)

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == INDEX_DAILY_REPAIR_MAX_TASK_RUNS_PER_ROUND
    assert all(len(run.filters_json["ts_code"].split(",")) == INDEX_DAILY_REPAIR_BATCH_SIZE for run in task_runs)
    assert {run.request_payload_json["missing_code_count"] for run in task_runs} == {2500}


def test_index_daily_repair_skips_codes_already_pending(db_session) -> None:
    trade_date = date(2026, 4, 24)
    active_codes = ["000001.SH", "399001.SZ", "399300.SZ"]
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, active_codes, trade_date=trade_date)
    _seed_raw_rows(db_session, active_codes, trade_date=trade_date)
    source_run = _create_source_run(db_session, trade_date=trade_date)
    pending = TaskRun(
        task_type="dataset_action",
        resource_key="index_daily",
        action="maintain",
        title="指数日线行情",
        trigger_source="system",
        status="queued",
        time_input_json={"mode": "point", "trade_date": "2026-04-24"},
        filters_json={"ts_code": "000001.SH,399001.SZ"},
        request_payload_json={"run_scope": INDEX_DAILY_GAP_REPAIR_RUN_SCOPE},
        requested_at=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
        queued_at=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
    )
    db_session.add(pending)
    db_session.commit()

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    assert task_runs[0].filters_json == {"ts_code": "399300.SZ"}


def test_index_daily_repair_does_not_create_historical_tasks(db_session) -> None:
    trade_date = date(2026, 4, 22)
    _seed_open_day(db_session, trade_date)
    _seed_open_day(db_session, date(2026, 4, 23))
    _seed_open_day(db_session, date(2026, 4, 24))
    _seed_active_indexes(db_session, ["399300.SZ"], trade_date=trade_date)
    source_run = _create_source_run(db_session, trade_date=trade_date)

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert task_runs == []
    assert db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "index_daily")) is None


def test_date_completeness_worker_creates_index_daily_repair_after_today_gap(db_session) -> None:
    trade_date = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date()
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, ["000001.SH", "399001.SZ"], trade_date=trade_date)
    _seed_serving_rows(db_session, ["000001.SH"], trade_date=trade_date)
    _seed_raw_rows(db_session, ["000001.SH", "399001.SZ"], trade_date=trade_date)
    DateCompletenessRunCommandService().create_system_run(
        db_session,
        dataset_key="index_daily",
        start_date=trade_date,
        end_date=trade_date,
    )

    run = DateCompletenessAuditWorker().run_next(db_session)

    assert run is not None
    assert run.dataset_key == "index_daily"
    assert run.run_status == "succeeded"
    assert run.result_status == "failed"
    assert run.missing_cell_count == 1
    repair_task = db_session.scalar(select(TaskRun).where(TaskRun.resource_key == "index_daily"))
    assert repair_task is not None
    assert repair_task.action == "maintain"
    assert repair_task.trigger_source == "system"
    assert repair_task.time_input_json == {"mode": "point", "trade_date": trade_date.isoformat()}
    assert repair_task.filters_json == {"ts_code": "399001.SZ"}
    assert repair_task.request_payload_json["run_scope"] == INDEX_DAILY_GAP_REPAIR_RUN_SCOPE
    assert repair_task.request_payload_json["repair_slot"] == INDEX_DAILY_REPAIR_SLOT_SAME_DAY_INITIAL
    assert repair_task.request_payload_json["source_date_completeness_run_id"] == run.id


def test_index_daily_repair_allows_the_previous_open_day(db_session) -> None:
    target_trade_date = date(2026, 4, 23)
    _seed_open_day(db_session, target_trade_date)
    _seed_open_day(db_session, date(2026, 4, 24))
    _seed_active_indexes(db_session, ["399300.SZ"], trade_date=target_trade_date)
    _seed_raw_rows(db_session, ["399300.SZ"], trade_date=target_trade_date)
    source_run = _create_source_run(db_session, trade_date=target_trade_date)

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    assert task_runs[0].time_input_json == {"mode": "point", "trade_date": "2026-04-23"}
    assert task_runs[0].request_payload_json["repair_slot"] == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_AFTERNOON


def test_index_daily_repair_uses_source_audit_time_for_previous_open_day_slot(db_session) -> None:
    target_trade_date = date(2026, 4, 23)
    _seed_open_day(db_session, date(2026, 4, 22))
    _seed_open_day(db_session, target_trade_date)
    _seed_open_day(db_session, date(2026, 4, 24))
    _seed_active_indexes(db_session, ["399300.SZ"], trade_date=target_trade_date)
    _seed_raw_rows(db_session, ["399300.SZ"], trade_date=date(2026, 4, 22))
    source_run = _create_source_run(
        db_session,
        trade_date=target_trade_date,
        requested_at=datetime(2026, 4, 24, 2, 0, tzinfo=timezone.utc),
    )

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 7, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    assert task_runs[0].request_payload_json["repair_slot"] == INDEX_DAILY_REPAIR_SLOT_PREVIOUS_OPEN_DAY_MORNING


def test_index_daily_repair_keeps_manual_audits_outside_automatic_slots(db_session) -> None:
    trade_date = date(2026, 4, 24)
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, ["399300.SZ"], trade_date=trade_date)
    _seed_raw_rows(db_session, ["399300.SZ"], trade_date=trade_date)
    source_run = _create_source_run(
        db_session,
        trade_date=trade_date,
        run_mode="manual",
        requested_by_user_id=1,
    )

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    assert "repair_slot" not in task_runs[0].request_payload_json


def test_index_daily_repair_keeps_configured_audits_outside_automatic_slots(db_session) -> None:
    trade_date = date(2026, 4, 24)
    _seed_open_day(db_session, trade_date)
    _seed_active_indexes(db_session, ["399300.SZ"], trade_date=trade_date)
    _seed_raw_rows(db_session, ["399300.SZ"], trade_date=trade_date)
    source_run = _create_source_run(
        db_session,
        trade_date=trade_date,
        schedule_id=7,
    )

    task_runs = IndexDailyCompletenessRepairService().create_repair_task_runs(
        db_session,
        source_run=source_run,
        now=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )

    assert len(task_runs) == 1
    assert "repair_slot" not in task_runs[0].request_payload_json
