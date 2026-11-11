"""Monthly wrapper uses the same coverage contract and natural month-end point."""

import dagster as dg

from orchestrator.defs.sensors.raw_stock_monthly_update_job_sensor import (
    evaluate_stock_monthly_update,
)
from tests.test_stock_period_native_daily import NOW
from tests.test_stock_period_native_daily import market as market  # noqa: PLC0414


def test_monthly_wrapper_submits_natural_month_end(market):
    with (
        dg.DagsterInstance.ephemeral() as instance,
        dg.build_sensor_context(
            instance=instance, resources={"lake_root": market.resource}
        ) as ctx,
    ):
        response = evaluate_stock_monthly_update(ctx, NOW)
        assert len(response.run_requests) == 1
        assert response.run_requests[0].partition_key == "2026-11"
        assert market.state["calls"][0][0]["trade_date"] == "20261130"
        assert market.state["calls"][0][1] == ("ts_code", "trade_date", "end_date")
