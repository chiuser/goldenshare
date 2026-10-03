from dataclasses import replace
from datetime import date
from threading import Event, Timer

import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.prod_db.stock_weekly import (
    build_prod_weekly_query,
    iter_prod_weekly_batches,
)
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklySource, WeeklyBudget

from .stock_weekly_capture_test_support import (
    FakeConnection,
    FakeResource,
    prod_frame,
    prod_plan,
)


def test_sql_preserves_business_columns_and_half_open_source_year():
    plan = prod_plan()
    sql, params = build_prod_weekly_query(plan.units[0], plan.budget)
    assert '"open"::text' in sql and "to_char(trade_date, 'YYYYMMDD')" in sql
    assert "freq = 'week'" in sql and "trade_date < %(end)s" in sql
    assert params["start"] == date(2020, 1, 1) and params["end"] == date(2021, 1, 1)
    for forbidden in (
        "SELECT *",
        "api_name",
        "fetched_at",
        "raw_payload",
        "is_listed",
        "IS NOT NULL",
    ):
        assert forbidden not in sql
    with pytest.raises(WeeklyCaptureError):
        build_prod_weekly_query(
            replace(plan.units[0], source=StockWeeklySource.ALTERNATE_WEEKLY),
            plan.budget,
        )
    with pytest.raises(WeeklyCaptureError):
        build_prod_weekly_query(replace(plan.units[0], schema_hash="bad"), plan.budget)


def test_snapshot_setup_streaming_and_control_count():
    budget = WeeklyBudget(fetch_batch_rows=1)
    unit = prod_plan(budget=budget).units[0]
    import pandas as pd

    frame = pd.concat(
        [prod_frame(trade_date="20200227"), prod_frame(trade_date="20200306")]
    )
    resource = FakeResource(FakeConnection(frame))
    evidence = {}
    batches = list(
        iter_prod_weekly_batches(resource, unit, budget, lambda: False, evidence)
    )
    assert len(batches) == 2 and batches[0].iloc[0]["close"] is None
    assert resource.connection.sessions == [
        {"isolation_level": "REPEATABLE READ", "readonly": True, "autocommit": False}
    ]
    assert resource.connection.fetch_sizes == [1, 1, 1]
    assert evidence["source_rows"] == 2 and evidence["snapshot"] == "100:200:"
    assert resource.connection_count == resource.connection.rollback_count == 1


def test_over_limit_stops_before_stream_and_count_mismatch_fails():
    plan = prod_plan()
    resource = FakeResource(FakeConnection(control_count=30001))
    with pytest.raises(WeeklyCaptureError, match="unit_row_budget"):
        list(
            iter_prod_weekly_batches(
                resource, plan.units[0], plan.budget, lambda: False, {}
            )
        )
    assert not resource.connection.fetch_sizes
    resource = FakeResource(FakeConnection(control_count=2))
    with pytest.raises(WeeklyCaptureError, match="source_count_changed"):
        list(
            iter_prod_weekly_batches(
                resource, plan.units[0], plan.budget, lambda: False, {}
            )
        )
    assert resource.connection.rollback_count == 1


def test_watchdog_interrupts_blocked_query_and_rolls_back():
    plan = prod_plan()
    canceled = Event()
    resource = FakeResource(FakeConnection(blocked=True))
    timer = Timer(0.3, canceled.set)
    timer.start()
    try:
        with pytest.raises(WeeklyCaptureError, match="canceled"):
            list(
                iter_prod_weekly_batches(
                    resource, plan.units[0], plan.budget, canceled.is_set, {}
                )
            )
    finally:
        timer.join()
    assert resource.connection.was_canceled and resource.connection.rollback_count == 1


def test_remaining_phase_budget_stops_before_fetch():
    plan = prod_plan()
    resource = FakeResource(FakeConnection(control_count=2))
    with pytest.raises(WeeklyCaptureError, match="phase_row_budget_exceeded"):
        list(
            iter_prod_weekly_batches(
                resource,
                plan.units[0],
                plan.budget,
                lambda: False,
                {},
                remaining_rows=1,
            )
        )
    assert not resource.connection.fetch_sizes
