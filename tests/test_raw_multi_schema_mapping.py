from __future__ import annotations

from src.foundation.models.raw_multi.raw_biying_equity_adj_factor import RawBiyingEquityAdjFactor
from src.foundation.models.raw_multi.raw_biying_equity_daily_bar import RawBiyingEquityDailyBar
from src.foundation.models.raw_multi.raw_biying_equity_daily_basic import RawBiyingEquityDailyBasic
from src.foundation.models.raw_multi.raw_tushare_equity_adj_factor import RawTushareEquityAdjFactor
from src.foundation.models.raw_multi.raw_tushare_equity_daily_bar import RawTushareEquityDailyBar
from src.foundation.models.raw_multi.raw_tushare_equity_daily_basic import RawTushareEquityDailyBasic


def test_raw_multi_models_schema_mapping() -> None:
    assert RawTushareEquityDailyBar.__table__.schema == "raw_tushare"
    assert RawTushareEquityAdjFactor.__table__.schema == "raw_tushare"
    assert RawTushareEquityDailyBasic.__table__.schema == "raw_tushare"

    assert RawBiyingEquityDailyBar.__table__.schema == "raw_biying"
    assert RawBiyingEquityAdjFactor.__table__.schema == "raw_biying"
    assert RawBiyingEquityDailyBasic.__table__.schema == "raw_biying"


def test_raw_multi_models_primary_keys() -> None:
    assert [column.name for column in RawTushareEquityDailyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in RawBiyingEquityAdjFactor.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in RawBiyingEquityDailyBasic.__table__.primary_key.columns] == ["ts_code", "trade_date"]
