from __future__ import annotations

from src.foundation.models.raw.raw_stock_basic import RawStockBasic
from src.foundation.models.raw_multi.raw_tushare_stock_basic import RawTushareStockBasic


def test_raw_tushare_stock_basic_has_same_columns_as_legacy_raw_stock_basic() -> None:
    raw_columns = [column.name for column in RawStockBasic.__table__.columns]
    raw_tushare_columns = [column.name for column in RawTushareStockBasic.__table__.columns]
    assert raw_tushare_columns == raw_columns
