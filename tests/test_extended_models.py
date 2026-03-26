from src.models.core.index_basic import IndexBasic
from src.models.core.index_daily_basic import IndexDailyBasic
from src.models.core.index_monthly_bar import IndexMonthlyBar
from src.models.core.index_weekly_bar import IndexWeeklyBar
from src.models.core.index_weight import IndexWeight
from src.models.core.security import Security
from src.models.core.stk_period_bar import StkPeriodBar
from src.models.core.stk_period_bar_adj import StkPeriodBarAdj


def test_security_includes_curr_type() -> None:
    assert "curr_type" in Security.__table__.columns


def test_stk_period_bar_primary_key_and_indexes() -> None:
    pk_columns = [column.name for column in StkPeriodBar.__table__.primary_key.columns]
    assert pk_columns == ["ts_code", "trade_date", "freq"]
    index_names = {index.name for index in StkPeriodBar.__table__.indexes}
    assert "idx_stk_period_bar_freq_trade_date" in index_names
    assert "idx_stk_period_bar_trade_date" in index_names


def test_stk_period_bar_adj_primary_key_and_indexes() -> None:
    pk_columns = [column.name for column in StkPeriodBarAdj.__table__.primary_key.columns]
    assert pk_columns == ["ts_code", "trade_date", "freq"]
    index_names = {index.name for index in StkPeriodBarAdj.__table__.indexes}
    assert "idx_stk_period_bar_adj_freq_trade_date" in index_names
    assert "idx_stk_period_bar_adj_trade_date" in index_names


def test_index_supplement_models_match_expected_keys() -> None:
    assert [column.name for column in IndexBasic.__table__.primary_key.columns] == ["ts_code"]
    assert [column.name for column in IndexWeeklyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexMonthlyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexWeight.__table__.primary_key.columns] == ["index_code", "trade_date", "con_code"]
    assert [column.name for column in IndexDailyBasic.__table__.primary_key.columns] == ["ts_code", "trade_date"]
