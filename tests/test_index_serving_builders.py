from __future__ import annotations

import pytest

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.index_daily_serving_builder import IndexDailyServingBuilder
from src.foundation.serving.builders.index_monthly_serving_builder import IndexMonthlyServingBuilder
from src.foundation.serving.builders.index_weekly_serving_builder import IndexWeeklyServingBuilder


@pytest.mark.parametrize(
    ("builder_cls", "dataset_key"),
    [
        (IndexDailyServingBuilder, "index_daily"),
        (IndexWeeklyServingBuilder, "index_weekly"),
        (IndexMonthlyServingBuilder, "index_monthly"),
    ],
)
def test_index_serving_builders_resolve_by_ts_code_and_trade_date(builder_cls, dataset_key: str) -> None:
    builder = builder_cls()
    policy = ResolutionPolicy(dataset_key=dataset_key, mode="primary", primary_source_key="tushare")
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [{"source_key": "tushare", "ts_code": "000001.SH", "trade_date": "2026-04-10", "close": 3310.2}]
        },
        policy=policy,
        active_sources={"tushare"},
        target_columns={"ts_code", "trade_date", "close", "source"},
    )

    assert result.resolved_count == 1
    row = result.rows[0]
    assert row["ts_code"] == "000001.SH"
    assert row["trade_date"] == "2026-04-10"
    assert row["source"] == "tushare"
