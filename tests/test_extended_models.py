from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, Numeric, SmallInteger, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
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
from src.foundation.models.core.equity_cyq_perf import EquityCyqPerf
from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core_serving.equity_auction_close import EquityAuctionClose
from src.foundation.models.core_serving.equity_auction_open import EquityAuctionOpen
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_nineturn import EquityNineTurn
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.core_serving.equity_margin_detail import EquityMarginDetail
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core_serving.wealth_market_turnover_snapshot import WealthMarketTurnoverSnapshot
from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily
from src.foundation.models.core_serving.wealth_sector_hierarchy import WealthSectorHierarchy
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core.us_security import UsSecurity
from src.foundation.models.raw.raw_dc_daily import RawDcDaily
from src.foundation.models.raw.raw_cyq_chips import RawCyqChips
from src.foundation.models.raw.raw_etf_sh_cons import RawEtfShCons
from src.foundation.models.raw.raw_stk_mins import RawStkMins
from src.foundation.models.raw.raw_stk_auction_c import RawStkAuctionC
from src.foundation.models.raw.raw_stk_auction_o import RawStkAuctionO
from src.foundation.models.raw.raw_index_mins import RawIndexMins
from src.foundation.models.raw.raw_index_basic import RawIndexBasic
from src.foundation.models.raw.raw_suspend_d import RawSuspendD
from src.foundation.models.raw.raw_ths_daily import RawThsDaily


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
    assert [column.name for column in BrokerRecommend.__table__.primary_key.columns] == ["month", "ts_code", "broker"]
    assert {index.name for index in BrokerRecommend.__table__.indexes} == {
        "idx_broker_recommend_month",
        "idx_broker_recommend_trade_date",
        "idx_broker_recommend_ts_code_month",
    }
    assert [column.name for column in IndexBasic.__table__.primary_key.columns] == ["ts_code"]
    assert str(RawIndexBasic.__table__.columns["base_date"].type) == "VARCHAR(16)"
    assert str(IndexBasic.__table__.columns["base_date"].type) == "DATE"
    assert [column.name for column in IndexWeeklyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexMonthlyBar.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in IndexWeight.__table__.primary_key.columns] == ["index_code", "trade_date", "con_code"]
    assert [column.name for column in IndexDailyBasic.__table__.primary_key.columns] == ["ts_code", "trade_date"]


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
    assert "pe_ttm" in RawThsDaily.__table__.columns
    assert "pb_mrq" in RawThsDaily.__table__.columns
    assert "pe_ttm" in ThsDaily.__table__.columns
    assert "pb_mrq" in ThsDaily.__table__.columns
    assert [column.name for column in DcIndex.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in DcMember.__table__.primary_key.columns] == ["trade_date", "ts_code", "con_code"]
    assert [column.name for column in RawDcDaily.__table__.primary_key.columns] == ["ts_code", "trade_date", "category"]
    assert [column.name for column in DcDaily.__table__.primary_key.columns] == ["ts_code", "trade_date", "category"]
    assert "category" in RawDcDaily.__table__.columns
    assert "category" in DcDaily.__table__.columns


def test_stk_limit_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityStkLimit.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in EquityStkLimit.__table__.indexes} == {"idx_equity_stk_limit_trade_date"}


def test_stock_auction_models_match_expected_keys() -> None:
    assert [column.name for column in RawStkAuctionO.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in RawStkAuctionC.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in EquityAuctionOpen.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert [column.name for column in EquityAuctionClose.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in RawStkAuctionO.__table__.indexes} == {
        "idx_raw_tushare_stk_auction_o_trade_date"
    }
    assert {index.name for index in RawStkAuctionC.__table__.indexes} == {
        "idx_raw_tushare_stk_auction_c_trade_date"
    }
    assert {index.name for index in EquityAuctionOpen.__table__.indexes} == {
        "idx_equity_auction_open_trade_date"
    }
    assert {index.name for index in EquityAuctionClose.__table__.indexes} == {
        "idx_equity_auction_close_trade_date"
    }


def test_stock_st_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityStockSt.__table__.primary_key.columns] == ["ts_code", "trade_date", "type"]
    assert {index.name for index in EquityStockSt.__table__.indexes} == {
        "idx_equity_stock_st_trade_date",
        "idx_equity_stock_st_ts_code_trade_date",
    }


def test_suspend_d_models_match_expected_keys_and_lengths() -> None:
    assert [column.name for column in EquitySuspendD.__table__.primary_key.columns] == ["id"]
    assert {index.name for index in EquitySuspendD.__table__.indexes} == {
        "uq_equity_suspend_d_row_key_hash",
        "idx_equity_suspend_d_trade_date",
        "idx_equity_suspend_d_ts_code_trade_date",
    }
    assert RawSuspendD.__table__.columns["suspend_timing"].type.length == 128
    assert EquitySuspendD.__table__.columns["suspend_timing"].type.length == 128


def test_stk_nineturn_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityNineTurn.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in EquityNineTurn.__table__.indexes} == {"idx_equity_nineturn_trade_date"}


def test_margin_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityMargin.__table__.primary_key.columns] == ["trade_date", "exchange_id"]
    assert {index.name for index in EquityMargin.__table__.indexes} == {
        "idx_equity_margin_trade_date",
        "idx_equity_margin_exchange_trade_date",
    }


def test_margin_detail_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityMarginDetail.__table__.primary_key.columns] == ["trade_date", "ts_code"]
    assert {index.name for index in EquityMarginDetail.__table__.indexes} == {
        "idx_equity_margin_detail_trade_date",
        "idx_equity_margin_detail_ts_code_trade_date_desc",
    }
    assert EquityMarginDetail.__table__.columns["name"].nullable is True


def test_cyq_perf_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityCyqPerf.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in EquityCyqPerf.__table__.indexes} == {
        "idx_equity_cyq_perf_trade_date",
        "idx_equity_cyq_perf_ts_code_trade_date",
    }


def test_cyq_chips_raw_model_matches_expected_keys() -> None:
    assert [column.name for column in RawCyqChips.__table__.primary_key.columns] == ["ts_code", "trade_date", "price"]
    assert {index.name for index in RawCyqChips.__table__.indexes} == {
        "idx_raw_tushare_cyq_chips_trade_date",
        "idx_raw_tushare_cyq_chips_ts_code_trade_date",
    }
    assert isinstance(RawCyqChips.__table__.columns["price"].type, Numeric)
    assert isinstance(RawCyqChips.__table__.columns["percent"].type, Numeric)


def test_etf_sh_cons_raw_model_matches_expected_keys() -> None:
    assert [column.name for column in RawEtfShCons.__table__.primary_key.columns] == [
        "trade_date",
        "ts_code",
        "con_code",
    ]
    assert {index.name for index in RawEtfShCons.__table__.indexes} == {
        "idx_raw_tushare_etf_sh_cons_trade_date",
        "idx_raw_tushare_etf_sh_cons_ts_code_trade_date",
        "idx_raw_tushare_etf_sh_cons_con_code",
    }
    assert isinstance(RawEtfShCons.__table__.columns["qty"].type, Numeric)
    assert isinstance(RawEtfShCons.__table__.columns["cpr"].type, String)
    assert isinstance(RawEtfShCons.__table__.columns["rdr"].type, String)
    assert isinstance(RawEtfShCons.__table__.columns["sca"].type, String)


def test_stk_factor_pro_serving_model_matches_expected_keys() -> None:
    assert [column.name for column in EquityFactorPro.__table__.primary_key.columns] == ["ts_code", "trade_date"]
    assert {index.name for index in EquityFactorPro.__table__.indexes} == {
        "idx_equity_factor_pro_trade_date",
        "idx_equity_factor_pro_ts_code_trade_date",
    }


def test_stk_mins_vol_uses_bigint() -> None:
    assert isinstance(RawStkMins.__table__.columns["vol"].type, BigInteger)


def test_wealth_market_turnover_snapshot_total_vol_uses_bigint() -> None:
    assert isinstance(WealthMarketTurnoverSnapshot.__table__.columns["total_vol"].type, BigInteger)


def test_wealth_sector_hierarchy_model_matches_frozen_contract() -> None:
    table = WealthSectorHierarchy.__table__

    assert table.schema == "core_serving"
    assert [column.name for column in table.primary_key.columns] == ["sector_code"]
    assert list(table.columns) == [
        table.columns["sector_code"],
        table.columns["sector_name"],
        table.columns["industry_level"],
        table.columns["industry_level_name"],
        table.columns["parent_sector_code"],
        table.columns["parent_sector_name"],
        table.columns["root_sector_code"],
        table.columns["root_sector_name"],
        table.columns["hierarchy_path"],
        table.columns["is_leaf"],
        table.columns["display_order"],
        table.columns["baseline_version"],
        table.columns["source_received_date"],
        table.columns["code_reference_trade_date"],
        table.columns["published_at"],
    ]
    assert isinstance(table.columns["industry_level"].type, SmallInteger)
    assert isinstance(table.columns["is_leaf"].type, Boolean)
    assert isinstance(table.columns["display_order"].type, Integer)
    assert isinstance(table.columns["source_received_date"].type, Date)
    assert isinstance(table.columns["published_at"].type, DateTime)
    assert table.columns["published_at"].type.timezone is True
    assert table.columns["parent_sector_code"].nullable is True
    assert table.columns["parent_sector_name"].nullable is True
    assert all(
        not table.columns[name].nullable
        for name in table.columns.keys()
        if name not in {"parent_sector_code", "parent_sector_name"}
    )
    assert {index.name for index in table.indexes} == {
        "idx_wealth_sector_hierarchy_level_order_code",
        "idx_wealth_sector_hierarchy_parent_level_order_code",
        "idx_wealth_sector_hierarchy_root_level_order_code",
    }
    assert {constraint.name for constraint in table.constraints} == {
        "pk_wealth_sector_hierarchy",
        "ck_wealth_sector_hierarchy_industry_level_range",
        "ck_wealth_sector_hierarchy_display_order_non_negative",
        "ck_wealth_sector_hierarchy_parent_fields_by_level",
    }


def test_wealth_sector_heat_daily_model_matches_frozen_contract() -> None:
    table = WealthSectorHeatDaily.__table__

    assert table.schema == "core_serving"
    assert [column.name for column in table.primary_key.columns] == ["trade_date", "sector_code"]
    assert isinstance(table.columns["base_heat_score"].type, Numeric)
    assert table.columns["base_heat_score"].type.precision == 8
    assert table.columns["base_heat_score"].type.scale == 4
    assert isinstance(table.columns["price_strength_score"].type, Numeric)
    assert table.columns["price_strength_score"].type.precision == 8
    assert table.columns["price_strength_score"].type.scale == 6
    assert isinstance(table.columns["quote_coverage"].type, Numeric)
    assert table.columns["quote_coverage"].type.precision == 8
    assert table.columns["quote_coverage"].type.scale == 6
    assert table.columns["source_dates_json"].type.compile(dialect=postgresql.dialect()) == "JSONB"
    assert table.columns["source_row_counts_json"].type.compile(dialect=postgresql.dialect()) == "JSONB"
    assert table.columns["invalid_reason"].nullable is True
    assert all(
        table.columns[name].nullable
        for name in (
            "base_heat_score",
            "base_heat_rank",
            "heat_score",
            "heat_rank",
            "heat_delta_1d",
            "price_strength_score",
            "breadth_score",
            "capital_flow_score",
            "activity_score",
            "persistence_score",
        )
    )
    assert {constraint.name for constraint in table.constraints} == {
        "pk_wealth_sector_heat_daily",
        "ck_wealth_sector_heat_daily_heat_status_allowed",
        "ck_wealth_sector_heat_daily_status_reason_consistent",
        "ck_wealth_sector_heat_daily_heat_level_allowed",
        "ck_wealth_sector_heat_daily_heat_trend_allowed",
        "ck_wealth_sector_heat_daily_raw_heat_trend_allowed",
        "ck_wealth_sector_heat_daily_valid_metrics_present",
        "ck_wealth_sector_heat_daily_invalid_outputs_empty",
        "ck_wealth_sector_heat_daily_heat_scores_range",
        "ck_wealth_sector_heat_daily_component_scores_range",
        "ck_wealth_sector_heat_daily_heat_ranks_positive",
        "ck_wealth_sector_heat_daily_member_counts_non_negative",
        "ck_wealth_sector_heat_daily_suspended_count_within_members",
        "ck_wealth_sector_heat_daily_quote_eligible_count_consistent",
        "ck_wealth_sector_heat_daily_valid_quote_count_within_eligible",
        "ck_wealth_sector_heat_daily_missing_quote_count_consistent",
        "ck_wealth_sector_heat_daily_config_hash_sha256",
        "ck_wealth_sector_heat_daily_source_hash_sha256",
    }

    index_ddl = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in table.indexes
    }
    assert "trade_date, heat_score DESC, sector_code" in index_ddl[
        "idx_wealth_sector_heat_daily_trade_score_code"
    ]
    assert "trade_date, heat_delta_1d DESC, sector_code" in index_ddl[
        "idx_wealth_sector_heat_daily_trade_delta_code"
    ]
    assert "sector_code, trade_date DESC" in index_ddl["idx_wealth_sector_heat_daily_sector_trade"]


def test_index_mins_keeps_freq_as_source_string_and_float_volume() -> None:
    assert [column.name for column in RawIndexMins.__table__.primary_key.columns] == ["ts_code", "freq", "trade_time"]
    assert isinstance(RawIndexMins.__table__.columns["freq"].type, String)
    assert isinstance(RawIndexMins.__table__.columns["vol"].type, Float)
