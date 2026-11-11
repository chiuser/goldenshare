"""Current weekly entrypoint: 20:00, verified source, current-period only."""

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import paths
from orchestrator.defs.io.stock_period_raw import connection
from orchestrator.defs.sensors.raw_stock_weekly_update_job_sensor import (
    evaluate_stock_weekly_update,
)
from tests.test_stock_period_native_daily import NOW
from tests.test_stock_period_native_daily import market as market  # noqa: PLC0414


def test_weekly_wrapper_submits_only_current_period(market):
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        result = evaluate_stock_weekly_update(ctx, NOW)
        assert len(result.run_requests) == 1
        request = result.run_requests[0]
        assert request.partition_key == "2026-11-13"
        assert request.run_config["ops"]["raw_tushare_stk_period_bar_adj_week"][
            "config"
        ] == {"intent": "daily", "automatic_intent_date": "2026-11-10"}


def test_sensor_rejects_raw_calendar_contract_without_source_call(market):
    calendar = paths.silver_trade_calendar_path(market.root)
    with connection(market.tmp / "wrong_calendar") as con:
        con.execute(
            "COPY (SELECT 'SSE' exchange,DATE '2026-11-10' cal_date,true is_open) TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
        pytest.raises(duckdb.BinderException, match="trade_date"),
    ):
        evaluate_stock_weekly_update(ctx, NOW)
    assert not market.state["calls"]


def test_sensor_skips_closed_day_before_source(market):
    calendar = paths.silver_trade_calendar_path(market.root)
    with connection(market.tmp / "closed_calendar") as con:
        con.execute(
            "COPY (SELECT 'SSE' exchange,DATE '2026-11-10' trade_date,false is_open) TO ? (FORMAT PARQUET)",
            [str(calendar)],
        )
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        assert not evaluate_stock_weekly_update(ctx, NOW).run_requests
    assert not market.state["calls"]
