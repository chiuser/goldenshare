from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.equity_price_restore_factor import EquityPriceRestoreFactor
from src.foundation.models.core.broker_recommend import BrokerRecommend
from src.foundation.models.core.etf_index import EtfIndex
from src.foundation.models.core.hk_security import HkSecurity
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_monthly_bar import IndexMonthlyBar
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.indicator_kdj import IndicatorKdj
from src.foundation.models.core.indicator_macd import IndicatorMacd
from src.foundation.models.core.indicator_meta import IndicatorMeta
from src.foundation.models.core.indicator_rsi import IndicatorRsi
from src.foundation.models.core.indicator_state import IndicatorState
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core.us_security import UsSecurity


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
    assert [column.name for column in EtfBasic.__table__.primary_key.columns] == ["ts_code"]
    assert {index.name for index in EtfBasic.__table__.indexes} == {
        "idx_etf_basic_index_code",
        "idx_etf_basic_exchange",
        "idx_etf_basic_mgr_name",
        "idx_etf_basic_list_status",
    }
    assert [column.name for column in EtfIndex.__table__.primary_key.columns] == ["ts_code"]
    assert {index.name for index in EtfIndex.__table__.indexes} == {
        "idx_etf_index_pub_date",
        "idx_etf_index_base_date",
    }
    assert [column.name for column in FundAdjFactor.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in FundAdjFactor.__table__.indexes} == {"idx_fund_adj_factor_trade_date"}
    assert [column.name for column in EquityPriceRestoreFactor.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in EquityPriceRestoreFactor.__table__.indexes} == {
        "idx_equity_price_restore_factor_trade_date",
        "idx_equity_price_restore_factor_updated_at",
    }
    assert [column.name for column in BrokerRecommend.__table__.primary_key.columns] == ["month", "ts_code", "broker"]
    assert {index.name for index in BrokerRecommend.__table__.indexes} == {
        "idx_broker_recommend_month",
        "idx_broker_recommend_trade_date",
        "idx_broker_recommend_ts_code_month",
    }
    assert [column.name for column in IndexBasic.__table__.primary_key.columns] == ["ts_code"]
    assert [column.name for column in IndexWeeklyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexMonthlyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexWeight.__table__.primary_key.columns] == ["index_code", "trade_date", "con_code"]
    assert [column.name for column in IndexDailyBasic.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndicatorMeta.__table__.primary_key.columns] == ["indicator_name", "version"]
    assert [column.name for column in IndicatorState.__table__.primary_key.columns] == [
        "ts_code",
        "source_key",
        "adjustment",
        "indicator_name",
        "version",
    ]
    assert [column.name for column in IndicatorMacd.__table__.primary_key.columns] == [
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]
    assert [column.name for column in IndicatorKdj.__table__.primary_key.columns] == [
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]
    assert [column.name for column in IndicatorRsi.__table__.primary_key.columns] == [
        "ts_code",
        "trade_date",
        "adjustment",
        "version",
    ]


def test_overseas_basic_models_match_expected_keys() -> None:
    assert [column.name for column in HkSecurity.__table__.primary_key.columns] == ["ts_code"]
    assert {index.name for index in HkSecurity.__table__.indexes} == {
        "idx_hk_security_name",
        "idx_hk_security_market",
        "idx_hk_security_list_status",
    }
    assert [column.name for column in UsSecurity.__table__.primary_key.columns] == ["ts_code"]
    assert {index.name for index in UsSecurity.__table__.indexes} == {
        "idx_us_security_name",
        "idx_us_security_classify",
        "idx_us_security_list_date",
    }


def test_board_dataset_models_match_expected_keys() -> None:
    assert [column.name for column in ThsIndex.__table__.primary_key.columns] == ["ts_code"]
    assert [column.name for column in ThsMember.__table__.primary_key.columns] == ["ts_code", "con_code"]
    assert [column.name for column in ThsDaily.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in DcIndex.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in DcMember.__table__.primary_key.columns] == ["trade_date", "ts_code", "con_code"]
    assert [column.name for column in DcDaily.__table__.primary_key.columns] == ["ts_code", "trade_date"]
