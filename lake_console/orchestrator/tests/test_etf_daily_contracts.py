from datetime import date, datetime, timezone

import pytest

from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_FUND_ADJ_SCHEMA,
    RAW_TUSHARE_FUND_DAILY_SCHEMA,
    SILVER_ETF_ADJ_FACTOR_SCHEMA,
    SILVER_ETF_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_ADJ_FACTOR_DATASET_ID,
    ETF_DAILY_DATASET_ID,
    ETF_DAILY_REJECTION_REASON_CODES,
    FUND_ADJ_DATASET_ID,
    FUND_ADJ_PAGE_LIMIT,
    FUND_ADJ_REQUEST_POLICY,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_DATASET_ID,
    FUND_DAILY_PAGE_LIMIT,
    FUND_DAILY_REQUEST_POLICY,
    FUND_DAILY_SOURCE_COLUMNS,
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_ADJ_JOB_NAME,
    RAW_FUND_ADJ_SENSOR_NAME,
    RAW_FUND_DAILY_CHECKS,
    RAW_FUND_DAILY_JOB_NAME,
    RAW_FUND_DAILY_SENSOR_NAME,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    SILVER_ETF_DAILY_JOB_NAME,
    SILVER_ETF_DAILY_SENSOR_NAME,
    EtfDailyContractError,
    build_fund_adj_request,
    build_fund_daily_request,
    normalize_etf_daily_trade_date,
)


def _schema_pairs(schema):  # type: ignore[no-untyped-def]
    return tuple((column.name, column.type) for column in schema)


def test_source_columns_and_page_limits_are_frozen() -> None:
    assert FUND_DAILY_SOURCE_COLUMNS == (
        "ts_code",
        "trade_date",
        "pre_close",
        "open",
        "high",
        "low",
        "close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    )
    assert FUND_ADJ_SOURCE_COLUMNS == (
        "ts_code",
        "trade_date",
        "adj_factor",
        "discount_rate",
    )
    assert FUND_DAILY_PAGE_LIMIT == 5_000
    assert FUND_ADJ_PAGE_LIMIT == 2_000
    assert "change_amount" not in FUND_DAILY_SOURCE_COLUMNS


def test_source_requests_use_only_one_trade_date_and_frozen_pagination() -> None:
    daily = build_fund_daily_request("2026-09-01", 5_000)
    adj = build_fund_adj_request("2026-09-01", 2_000)

    assert daily.api_name == "fund_daily"
    assert daily.params == {
        "trade_date": "20260901",
        "limit": 5_000,
        "offset": 5_000,
    }
    assert daily.fields == FUND_DAILY_SOURCE_COLUMNS
    assert adj.api_name == "fund_adj"
    assert adj.params == {
        "trade_date": "20260901",
        "limit": 2_000,
        "offset": 2_000,
    }
    assert adj.fields == FUND_ADJ_SOURCE_COLUMNS
    assert set(daily.params).isdisjoint({"ts_code", "start_date", "end_date"})
    assert set(adj.params).isdisjoint({"ts_code", "start_date", "end_date"})


@pytest.mark.parametrize("offset", [-1, 1, 2_000, True, 5_000.0])
def test_fund_daily_request_rejects_invalid_offsets(offset: object) -> None:
    with pytest.raises(EtfDailyContractError, match="offset"):
        build_fund_daily_request("2026-09-01", offset)  # type: ignore[arg-type]


@pytest.mark.parametrize("offset", [-1, 1, 5_000, True, 2_000.0])
def test_fund_adj_request_rejects_invalid_offsets(offset: object) -> None:
    with pytest.raises(EtfDailyContractError, match="offset"):
        build_fund_adj_request("2026-09-01", offset)  # type: ignore[arg-type]


def test_request_budgets_and_raw_check_names_are_frozen() -> None:
    assert FUND_DAILY_REQUEST_POLICY.max_retries == 1
    assert FUND_DAILY_REQUEST_POLICY.max_requests == 2
    assert FUND_DAILY_REQUEST_POLICY.max_elapsed_seconds == 30.0
    assert FUND_ADJ_REQUEST_POLICY.max_retries == 1
    assert FUND_ADJ_REQUEST_POLICY.max_requests == 4
    assert FUND_ADJ_REQUEST_POLICY.max_elapsed_seconds == 30.0
    assert FUND_DAILY_REQUEST_POLICY.minimum_interval_seconds == 0.13
    assert FUND_ADJ_REQUEST_POLICY.minimum_interval_seconds == 0.13
    assert RAW_FUND_DAILY_CHECKS == (
        "raw_tushare_fund_daily_source_contract_check",
        "raw_tushare_fund_daily_partition_scope_check",
        "raw_tushare_fund_daily_key_integrity_check",
    )
    assert RAW_FUND_ADJ_CHECKS == (
        "raw_tushare_fund_adj_source_contract_check",
        "raw_tushare_fund_adj_partition_scope_check",
        "raw_tushare_fund_adj_key_integrity_check",
    )


def test_raw_and_silver_schemas_only_cast_trade_date() -> None:
    assert _schema_pairs(RAW_TUSHARE_FUND_DAILY_SCHEMA) == tuple(
        (
            column,
            "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE",
        )
        for column in FUND_DAILY_SOURCE_COLUMNS
    )
    assert _schema_pairs(SILVER_ETF_DAILY_SCHEMA) == tuple(
        (
            column,
            "DATE"
            if column == "trade_date"
            else "VARCHAR"
            if column == "ts_code"
            else "DOUBLE",
        )
        for column in FUND_DAILY_SOURCE_COLUMNS
    )
    assert _schema_pairs(RAW_TUSHARE_FUND_ADJ_SCHEMA) == (
        ("ts_code", "VARCHAR"),
        ("trade_date", "VARCHAR"),
        ("adj_factor", "DOUBLE"),
        ("discount_rate", "DOUBLE"),
    )
    assert _schema_pairs(SILVER_ETF_ADJ_FACTOR_SCHEMA) == (
        ("ts_code", "VARCHAR"),
        ("trade_date", "DATE"),
        ("adj_factor", "DOUBLE"),
        ("discount_rate", "DOUBLE"),
    )
    assert all(
        column.description
        for schema in (
            RAW_TUSHARE_FUND_DAILY_SCHEMA,
            SILVER_ETF_DAILY_SCHEMA,
            RAW_TUSHARE_FUND_ADJ_SCHEMA,
            SILVER_ETF_ADJ_FACTOR_SCHEMA,
        )
        for column in schema
    )


def test_trade_date_normalization_is_strict() -> None:
    assert normalize_etf_daily_trade_date("2026-09-01") == "2026-09-01"
    assert normalize_etf_daily_trade_date(date(2026, 9, 1)) == "2026-09-01"

    for invalid in (
        "20260901",
        "2026-9-1",
        "2026-02-30",
        datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
    ):
        with pytest.raises(EtfDailyContractError, match="trade date"):
            normalize_etf_daily_trade_date(invalid)  # type: ignore[arg-type]


def test_definition_names_and_dataset_names_are_stable() -> None:
    assert (
        RAW_FUND_DAILY_JOB_NAME,
        SILVER_ETF_DAILY_JOB_NAME,
        RAW_FUND_ADJ_JOB_NAME,
        SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    ) == (
        "raw_fund_daily_update_job",
        "silver_etf_daily_update_job",
        "raw_fund_adj_update_job",
        "silver_etf_adj_factor_update_job",
    )
    assert (
        RAW_FUND_DAILY_SENSOR_NAME,
        SILVER_ETF_DAILY_SENSOR_NAME,
        RAW_FUND_ADJ_SENSOR_NAME,
        SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    ) == tuple(
        f"{job_name}_sensor"
        for job_name in (
            RAW_FUND_DAILY_JOB_NAME,
            SILVER_ETF_DAILY_JOB_NAME,
            RAW_FUND_ADJ_JOB_NAME,
            SILVER_ETF_ADJ_FACTOR_JOB_NAME,
        )
    )
    assert {
        dataset_id: DATASET_CHINESE_NAMES[dataset_id]
        for dataset_id in (
            FUND_DAILY_DATASET_ID,
            ETF_DAILY_DATASET_ID,
            FUND_ADJ_DATASET_ID,
            ETF_ADJ_FACTOR_DATASET_ID,
        )
    } == {
        "fund_daily": "基金日线行情",
        "etf_daily": "ETF 日线行情",
        "fund_adj": "基金复权因子",
        "etf_adj_factor": "ETF 复权因子",
    }


def test_silver_rejection_reason_contract_is_frozen() -> None:
    assert ETF_DAILY_REJECTION_REASON_CODES == (
        "NON_EXCHANGE_SUFFIX",
        "BASIC_CODE_ABSENT",
        "EXCHANGE_MISMATCH",
        "STATUS_NOT_LISTED",
        "LIST_DATE_NULL",
        "LIST_DATE_AFTER_TRADE_DATE",
    )
