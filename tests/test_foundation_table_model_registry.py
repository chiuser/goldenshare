from __future__ import annotations

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.raw.raw_daily import RawDaily
from src.foundation.models.table_model_registry import get_model_by_table_name, table_model_registry


def test_table_model_registry_derives_models_from_sqlalchemy_metadata() -> None:
    assert get_model_by_table_name("core_serving.equity_daily_bar") is EquityDailyBar
    assert get_model_by_table_name("raw_tushare.daily") is RawDaily


def test_table_model_registry_excludes_ops_tables() -> None:
    assert "ops.task_run" not in table_model_registry()
