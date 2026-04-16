from src.foundation.services.sync.fields import (
    ADJ_FACTOR_FIELDS,
    BLOCK_TRADE_FIELDS,
    DAILY_BASIC_FIELDS,
    DAILY_FIELDS,
    DIVIDEND_FIELDS,
    ETF_BASIC_FIELDS,
    ETF_INDEX_FIELDS,
    FUND_ADJ_FIELDS,
    FUND_DAILY_FIELDS,
    BROKER_RECOMMEND_FIELDS,
    HOLDERNUMBER_FIELDS,
    HK_BASIC_FIELDS,
    LIMIT_CPT_LIST_FIELDS,
    LIMIT_LIST_THS_FIELDS,
    LIMIT_STEP_FIELDS,
    MARGIN_FIELDS,
    THS_INDEX_FIELDS,
    THS_MEMBER_FIELDS,
    THS_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_MEMBER_FIELDS,
    DC_DAILY_FIELDS,
    INDEX_BASIC_FIELDS,
    INDEX_DAILY_BASIC_FIELDS,
    INDEX_DAILY_FIELDS,
    INDEX_MONTHLY_FIELDS,
    INDEX_WEIGHT_FIELDS,
    INDEX_WEEKLY_FIELDS,
    LIMIT_LIST_FIELDS,
    STK_LIMIT_FIELDS,
    STK_NINETURN_FIELDS,
    SUSPEND_D_FIELDS,
    MONEYFLOW_FIELDS,
    STK_PERIOD_BAR_ADJ_FIELDS,
    STK_PERIOD_BAR_FIELDS,
    STOCK_BASIC_FIELDS,
    TOP_LIST_FIELDS,
    TRADE_CAL_FIELDS,
    US_BASIC_FIELDS,
)
from src.foundation.services.sync.sync_fund_daily_service import SyncFundDailyService
from src.foundation.services.sync.sync_index_daily_service import SyncIndexDailyService
from src.foundation.services.sync.sync_stock_basic_service import SyncStockBasicService


def test_existing_field_constants_are_wired_to_services() -> None:
    assert SyncStockBasicService.fields == STOCK_BASIC_FIELDS
    assert SyncFundDailyService.fields == FUND_DAILY_FIELDS
    assert SyncIndexDailyService.fields == INDEX_DAILY_FIELDS


def test_split_field_constants_are_explicit_lists() -> None:
    assert tuple(FUND_DAILY_FIELDS) == tuple(DAILY_FIELDS)
    assert tuple(INDEX_DAILY_FIELDS) == tuple(DAILY_FIELDS)
    assert FUND_DAILY_FIELDS is not DAILY_FIELDS
    assert INDEX_DAILY_FIELDS is not DAILY_FIELDS


def test_new_field_constants_exist() -> None:
    assert "freq" in STK_PERIOD_BAR_FIELDS
    assert "open_qfq" in STK_PERIOD_BAR_ADJ_FIELDS
    assert "publisher" in INDEX_BASIC_FIELDS
    assert tuple(HK_BASIC_FIELDS) == (
        "ts_code",
        "name",
        "fullname",
        "enname",
        "cn_spell",
        "market",
        "list_status",
        "list_date",
        "delist_date",
        "trade_unit",
        "isin",
        "curr_type",
    )
    assert tuple(US_BASIC_FIELDS) == (
        "ts_code",
        "name",
        "enname",
        "classify",
        "list_date",
        "delist_date",
    )
    assert tuple(ETF_BASIC_FIELDS) == (
        "ts_code",
        "csname",
        "extname",
        "cname",
        "index_code",
        "index_name",
        "setup_date",
        "list_date",
        "list_status",
        "exchange",
        "mgr_name",
        "custod_name",
        "mgt_fee",
        "etf_type",
    )
    assert tuple(ETF_INDEX_FIELDS) == (
        "ts_code",
        "indx_name",
        "indx_csname",
        "pub_party_name",
        "pub_date",
        "base_date",
        "bp",
        "adj_circle",
    )
    assert tuple(FUND_ADJ_FIELDS) == (
        "ts_code",
        "trade_date",
        "adj_factor",
    )
    assert tuple(BROKER_RECOMMEND_FIELDS) == (
        "month",
        "currency",
        "name",
        "ts_code",
        "trade_date",
        "close",
        "pct_change",
        "target_price",
        "industry",
        "broker",
        "broker_mkt",
        "author",
        "recom_type",
        "reason",
    )
    assert "trade_date" in INDEX_WEEKLY_FIELDS
    assert "trade_date" in INDEX_MONTHLY_FIELDS
    assert tuple(INDEX_WEIGHT_FIELDS) == ("index_code", "con_code", "trade_date", "weight")
    assert "pb" in INDEX_DAILY_BASIC_FIELDS
    assert tuple(THS_INDEX_FIELDS) == ("ts_code", "name", "count", "exchange", "list_date", "type")
    assert "con_code" in THS_MEMBER_FIELDS
    assert "avg_price" in THS_DAILY_FIELDS
    assert "idx_type" in DC_INDEX_FIELDS
    assert tuple(DC_MEMBER_FIELDS) == ("trade_date", "ts_code", "con_code", "name")
    assert "swing" in DC_DAILY_FIELDS
    assert "market_type" in LIMIT_LIST_THS_FIELDS
    assert tuple(LIMIT_STEP_FIELDS) == ("ts_code", "name", "trade_date", "nums")
    assert tuple(LIMIT_CPT_LIST_FIELDS) == ("ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank")


def test_existing_field_constants_still_cover_core_resources() -> None:
    assert "pretrade_date" in TRADE_CAL_FIELDS
    assert "adj_factor" in ADJ_FACTOR_FIELDS
    assert tuple(MARGIN_FIELDS) == (
        "trade_date",
        "exchange_id",
        "rzye",
        "rzmre",
        "rzche",
        "rqye",
        "rqmcl",
        "rzrqye",
        "rqyl",
    )
    assert "close" in DAILY_BASIC_FIELDS
    assert "net_mf_amount" in MONEYFLOW_FIELDS
    assert "reason" in TOP_LIST_FIELDS
    assert "seller" in BLOCK_TRADE_FIELDS
    assert "div_listdate" in DIVIDEND_FIELDS
    assert "base_date" in DIVIDEND_FIELDS
    assert "base_share" in DIVIDEND_FIELDS
    assert "holder_num" in HOLDERNUMBER_FIELDS
    assert "limit_times" in LIMIT_LIST_FIELDS
    assert tuple(STK_LIMIT_FIELDS) == ("trade_date", "ts_code", "pre_close", "up_limit", "down_limit")
    assert tuple(SUSPEND_D_FIELDS) == ("ts_code", "trade_date", "suspend_timing", "suspend_type")
    assert tuple(STK_NINETURN_FIELDS) == (
        "ts_code",
        "trade_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
    )
