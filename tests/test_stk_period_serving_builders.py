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


@pytest.mark.parametrize('builder_cls,freq', [(StkPeriodBarAdjWeekServingBuilder,'week'),(StkPeriodBarAdjMonthServingBuilder,'month')])
def test_adjusted_builders_select_whole_latest_period_independent_of_source_priority(builder_cls,freq):
    from datetime import date
    from decimal import Decimal
    from test_stock_period_adj_contracts import literal_rows
    rows=literal_rows()
    if freq=='week':
        rows=[{**rows[0],'freq':'week','trade_date':date(2020,2,28)},
              {**rows[1],'freq':'week','trade_date':date(2020,2,27)}]
    policy=ResolutionPolicy(dataset_key='stk_period_bar_adj_'+freq,mode='primary',primary_source_key='old')
    result=builder_cls().build_rows(std_rows_by_source={'new':[rows[0]],'old':[rows[1]]},policy=policy,
        active_sources={'old'},target_columns={'ts_code','trade_date','freq','close_qfq','change_amount'})
    assert result.resolved_count==1 and result.rows[0]['trade_date']==rows[0]['trade_date']
    assert result.rows[0]['close_qfq']==Decimal('11.14') and result.rows[0]['change_amount']==Decimal('-1.04')
