from __future__ import annotations

from src.foundation.models.raw_multi.raw_biying_stock_basic import RawBiyingStockBasic
from src.foundation.models.raw_multi.raw_tushare_stock_basic import RawTushareStockBasic


def test_raw_multi_models_schema_mapping() -> None:
    assert RawTushareStockBasic.__table__.schema == "raw_tushare"
    assert RawBiyingStockBasic.__table__.schema == "raw_biying"


def test_raw_multi_models_primary_keys() -> None:
    assert [column.name for column in RawTushareStockBasic.__table__.primary_key.columns] == ["ts_code"]
    assert [column.name for column in RawBiyingStockBasic.__table__.primary_key.columns] == ["dm"]
