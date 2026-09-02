"""Stable contracts for Tushare fund daily and adjustment-factor assets."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

FUND_DAILY_API_NAME = "fund_daily"
FUND_ADJ_API_NAME = "fund_adj"
FUND_DAILY_PAGE_LIMIT = 5_000
FUND_ADJ_PAGE_LIMIT = 2_000

RAW_TUSHARE_FUND_DAILY_ASSET_KEY = "raw_tushare_fund_daily"
SILVER_ETF_DAILY_ASSET_KEY = "silver_etf_daily"
RAW_TUSHARE_FUND_ADJ_ASSET_KEY = "raw_tushare_fund_adj"
SILVER_ETF_ADJ_FACTOR_ASSET_KEY = "silver_etf_adj_factor"

FUND_DAILY_DATASET_ID = "fund_daily"
ETF_DAILY_DATASET_ID = "etf_daily"
FUND_ADJ_DATASET_ID = "fund_adj"
ETF_ADJ_FACTOR_DATASET_ID = "etf_adj_factor"

RAW_FUND_DAILY_JOB_NAME = "raw_fund_daily_update_job"
SILVER_ETF_DAILY_JOB_NAME = "silver_etf_daily_update_job"
RAW_FUND_ADJ_JOB_NAME = "raw_fund_adj_update_job"
SILVER_ETF_ADJ_FACTOR_JOB_NAME = "silver_etf_adj_factor_update_job"

RAW_FUND_DAILY_SENSOR_NAME = f"{RAW_FUND_DAILY_JOB_NAME}_sensor"
SILVER_ETF_DAILY_SENSOR_NAME = f"{SILVER_ETF_DAILY_JOB_NAME}_sensor"
RAW_FUND_ADJ_SENSOR_NAME = f"{RAW_FUND_ADJ_JOB_NAME}_sensor"
SILVER_ETF_ADJ_FACTOR_SENSOR_NAME = f"{SILVER_ETF_ADJ_FACTOR_JOB_NAME}_sensor"

ETF_DAILY_SENSOR_WINDOW_LIMIT = 10
ETF_DAILY_BOOTSTRAP_START_DATE = date(2025, 1, 1)
ETF_DAILY_BOOTSTRAP_BATCH_DAYS = 20
ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS = 20
ETF_DAILY_DISK_SAFETY_FACTOR = Decimal("2.5")
ETF_DAILY_AUTOMATION_CONTRACT_REVISION = "v1"
ETF_DAILY_CHANGE_TOLERANCE = 1e-6
ETF_DAILY_PCT_CHG_TOLERANCE = 0.01
ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT = 20

FUND_DAILY_SOURCE_COLUMNS = (
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

FUND_ADJ_SOURCE_COLUMNS = (
    "ts_code",
    "trade_date",
    "adj_factor",
    "discount_rate",
)

FUND_DAILY_RAW_COLUMN_TYPES = MappingProxyType(
    {
        column: "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE"
        for column in FUND_DAILY_SOURCE_COLUMNS
    }
)
FUND_DAILY_SILVER_COLUMN_TYPES = MappingProxyType(
    {
        column: "DATE"
        if column == "trade_date"
        else "VARCHAR"
        if column == "ts_code"
        else "DOUBLE"
        for column in FUND_DAILY_SOURCE_COLUMNS
    }
)
FUND_ADJ_RAW_COLUMN_TYPES = MappingProxyType(
    {
        column: "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE"
        for column in FUND_ADJ_SOURCE_COLUMNS
    }
)
FUND_ADJ_SILVER_COLUMN_TYPES = MappingProxyType(
    {
        column: "DATE"
        if column == "trade_date"
        else "VARCHAR"
        if column == "ts_code"
        else "DOUBLE"
        for column in FUND_ADJ_SOURCE_COLUMNS
    }
)

ETF_DAILY_REJECTION_REASON_CODES = (
    "NON_EXCHANGE_SUFFIX",
    "BASIC_CODE_ABSENT",
    "EXCHANGE_MISMATCH",
    "STATUS_NOT_LISTED",
    "LIST_DATE_NULL",
    "LIST_DATE_AFTER_TRADE_DATE",
)

RAW_FUND_DAILY_CHECKS = (
    "raw_tushare_fund_daily_source_contract_check",
    "raw_tushare_fund_daily_partition_scope_check",
    "raw_tushare_fund_daily_key_integrity_check",
)
RAW_FUND_ADJ_CHECKS = (
    "raw_tushare_fund_adj_source_contract_check",
    "raw_tushare_fund_adj_partition_scope_check",
    "raw_tushare_fund_adj_key_integrity_check",
)

FUND_DAILY_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=2,
    max_elapsed_seconds=30.0,
)
FUND_ADJ_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=4,
    max_elapsed_seconds=30.0,
)


class EtfDailyContractError(ValueError):
    """Raised when an ETF daily contract value is invalid."""


@dataclass(frozen=True, slots=True)
class EtfDailySourceRequest:
    api_name: str
    params: Mapping[str, object]
    fields: tuple[str, ...]


def normalize_etf_daily_trade_date(value: str | date) -> str:
    """Return one strict ISO trade date used by partitions and paths."""

    if isinstance(value, datetime):
        raise EtfDailyContractError("ETF daily trade date must not include a time")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise EtfDailyContractError(
            f"ETF daily trade date must use YYYY-MM-DD: {value!r}"
        ) from error
    if text != parsed.isoformat():
        raise EtfDailyContractError(
            f"ETF daily trade date must use YYYY-MM-DD: {value!r}"
        )
    return text


def _validated_offset(offset: int, *, page_limit: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise EtfDailyContractError("ETF daily offset must be an integer")
    if offset < 0 or offset % page_limit != 0:
        raise EtfDailyContractError(
            "ETF daily offset must be a non-negative multiple of the page limit"
        )
    return offset


def _build_source_request(
    *,
    api_name: str,
    source_columns: tuple[str, ...],
    page_limit: int,
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    trade_date = normalize_etf_daily_trade_date(partition_key)
    return EtfDailySourceRequest(
        api_name=api_name,
        params=MappingProxyType(
            {
                "trade_date": trade_date.replace("-", ""),
                "limit": page_limit,
                "offset": _validated_offset(offset, page_limit=page_limit),
            }
        ),
        fields=source_columns,
    )


def build_fund_daily_request(
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    return _build_source_request(
        api_name=FUND_DAILY_API_NAME,
        source_columns=FUND_DAILY_SOURCE_COLUMNS,
        page_limit=FUND_DAILY_PAGE_LIMIT,
        partition_key=partition_key,
        offset=offset,
    )


def build_fund_adj_request(
    partition_key: str | date,
    offset: int,
) -> EtfDailySourceRequest:
    return _build_source_request(
        api_name=FUND_ADJ_API_NAME,
        source_columns=FUND_ADJ_SOURCE_COLUMNS,
        page_limit=FUND_ADJ_PAGE_LIMIT,
        partition_key=partition_key,
        offset=offset,
    )
