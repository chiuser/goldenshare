from __future__ import annotations

from src.foundation.models.core_multi.equity_adj_factor_std import EquityAdjFactorStd
from src.foundation.models.core_multi.equity_daily_bar_std import EquityDailyBarStd
from src.foundation.models.core_multi.equity_daily_basic_std import EquityDailyBasicStd
from src.foundation.models.core_multi.stk_period_bar_adj_std import StkPeriodBarAdjStd
from src.foundation.models.core_multi.stk_period_bar_std import StkPeriodBarStd


def test_core_multi_models_schema_and_primary_keys() -> None:
    assert EquityDailyBarStd.__table__.schema == "core_multi"
    assert [column.name for column in EquityDailyBarStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
    ]

    assert EquityAdjFactorStd.__table__.schema == "core_multi"
    assert [column.name for column in EquityAdjFactorStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
    ]

    assert EquityDailyBasicStd.__table__.schema == "core_multi"
    assert [column.name for column in EquityDailyBasicStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
    ]

    assert [column.name for column in StkPeriodBarStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
        "freq",
    ]
    assert [column.name for column in StkPeriodBarAdjStd.__table__.primary_key.columns] == [
        "source_key",
        "ts_code",
        "trade_date",
        "freq",
    ]
