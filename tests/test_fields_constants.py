from src.services.sync.fields import (
    ADJ_FACTOR_FIELDS,
    BLOCK_TRADE_FIELDS,
    DAILY_BASIC_FIELDS,
    DAILY_FIELDS,
    DIVIDEND_FIELDS,
    ETF_BASIC_FIELDS,
    FUND_DAILY_FIELDS,
    HOLDERNUMBER_FIELDS,
    INDEX_BASIC_FIELDS,
    INDEX_DAILY_BASIC_FIELDS,
    INDEX_DAILY_FIELDS,
    INDEX_MONTHLY_FIELDS,
    INDEX_WEIGHT_FIELDS,
    INDEX_WEEKLY_FIELDS,
    LIMIT_LIST_FIELDS,
    MONEYFLOW_FIELDS,
    STK_PERIOD_BAR_ADJ_FIELDS,
    STK_PERIOD_BAR_FIELDS,
    STOCK_BASIC_FIELDS,
    TOP_LIST_FIELDS,
    TRADE_CAL_FIELDS,
)
from src.services.sync.sync_fund_daily_service import SyncFundDailyService
from src.services.sync.sync_index_daily_service import SyncIndexDailyService
from src.services.sync.sync_stock_basic_service import SyncStockBasicService


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
    assert "trade_date" in INDEX_WEEKLY_FIELDS
    assert "trade_date" in INDEX_MONTHLY_FIELDS
    assert tuple(INDEX_WEIGHT_FIELDS) == ("index_code", "con_code", "trade_date", "weight")
    assert "pb" in INDEX_DAILY_BASIC_FIELDS


def test_existing_field_constants_still_cover_core_resources() -> None:
    assert "pretrade_date" in TRADE_CAL_FIELDS
    assert "adj_factor" in ADJ_FACTOR_FIELDS
    assert "close" in DAILY_BASIC_FIELDS
    assert "net_mf_amount" in MONEYFLOW_FIELDS
    assert "reason" in TOP_LIST_FIELDS
    assert "seller" in BLOCK_TRADE_FIELDS
    assert "div_listdate" in DIVIDEND_FIELDS
    assert "base_date" in DIVIDEND_FIELDS
    assert "base_share" in DIVIDEND_FIELDS
    assert "holder_num" in HOLDERNUMBER_FIELDS
    assert "limit_times" in LIMIT_LIST_FIELDS
