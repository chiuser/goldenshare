from __future__ import annotations

import pytest

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.stk_period_bar_adj_month_serving_builder import StkPeriodBarAdjMonthServingBuilder
from src.foundation.serving.builders.stk_period_bar_adj_week_serving_builder import StkPeriodBarAdjWeekServingBuilder
from src.foundation.serving.builders.stk_period_bar_month_serving_builder import StkPeriodBarMonthServingBuilder
from src.foundation.serving.builders.stk_period_bar_week_serving_builder import StkPeriodBarWeekServingBuilder


@pytest.mark.parametrize(
    ("builder_cls", "dataset_key", "freq"),
    [
        (StkPeriodBarWeekServingBuilder, "stk_period_bar_week", "week"),
        (StkPeriodBarMonthServingBuilder, "stk_period_bar_month", "month"),
        (StkPeriodBarAdjWeekServingBuilder, "stk_period_bar_adj_week", "week"),
        (StkPeriodBarAdjMonthServingBuilder, "stk_period_bar_adj_month", "month"),
    ],
)
def test_stk_period_serving_builders_use_ts_trade_date_and_freq(builder_cls, dataset_key: str, freq: str) -> None:
    builder = builder_cls()
    policy = ResolutionPolicy(dataset_key=dataset_key, mode="primary", primary_source_key="tushare")
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [
                {
                    "source_key": "tushare",
                    "ts_code": "000001.SZ",
                    "trade_date": "2026-04-10",
                    "freq": freq,
                    "close": 12.3,
                }
            ]
        },
        policy=policy,
        active_sources={"tushare"},
        target_columns={"ts_code", "trade_date", "freq", "close", "source"},
    )

    assert result.resolved_count == 1
    row = result.rows[0]
    assert row["ts_code"] == "000001.SZ"
    assert row["trade_date"] == "2026-04-10"
    assert row["freq"] == freq
    assert row["source"] == "tushare"
