"""Approved daily-basic identity, decimal and request contracts."""

from datetime import date, time
from hashlib import sha256

from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

DAILY_BASIC_ASSET = "raw_tushare_daily_basic"
DAILY_BASIC_JOB = "raw_tushare_daily_basic_update_job"
DAILY_BASIC_PARTITIONS = "cn_a_daily_basic_trade_days"
DAILY_BASIC_HISTORY_START = "2010-01-04"
DAILY_BASIC_REGISTER_START = time(17, 0)
DAILY_BASIC_UPDATE_START = time(19, 0)
DAILY_BASIC_INTERVAL = 900
DAILY_BASIC_WINDOW = 10
DAILY_BASIC_PAGE_SIZE = 6000
DAILY_BASIC_CHECKS = (
    "raw_tushare_daily_basic_file_contract_check",
    "raw_tushare_daily_basic_source_coverage_check",
)
DAILY_BASIC_COLUMN_SPECS = (
    ("ts_code", "VARCHAR", "股票代码，不得为空"),
    ("trade_date", "VARCHAR", "原始交易日，YYYYMMDD"),
    ("close", "DECIMAL(18,4)", "当日收盘价，元"),
    ("turnover_rate", "DECIMAL(12,4)", "换手率，百分比原值"),
    ("turnover_rate_f", "DECIMAL(12,4)", "自由流通股换手率，百分比原值"),
    ("volume_ratio", "DECIMAL(12,4)", "量比，允许为空"),
    ("pe", "DECIMAL(18,4)", "市盈率，允许为空或负值"),
    ("pe_ttm", "DECIMAL(18,4)", "TTM市盈率，允许为空或负值"),
    ("pb", "DECIMAL(18,4)", "市净率，允许为空"),
    ("ps", "DECIMAL(18,4)", "市销率，允许为空或负值"),
    ("ps_ttm", "DECIMAL(18,4)", "TTM市销率，允许为空或负值"),
    ("dv_ratio", "DECIMAL(12,4)", "股息率，百分比原值"),
    ("dv_ttm", "DECIMAL(12,4)", "TTM股息率，百分比原值"),
    ("total_share", "DECIMAL(20,4)", "总股本，万股"),
    ("float_share", "DECIMAL(20,4)", "流通股本，万股"),
    ("free_share", "DECIMAL(20,4)", "自由流通股本，万股"),
    ("total_mv", "DECIMAL(20,4)", "总市值，万元"),
    ("circ_mv", "DECIMAL(20,4)", "流通市值，万元"),
)
DAILY_BASIC_FIELDS = tuple(item[0] for item in DAILY_BASIC_COLUMN_SPECS)
DAILY_BASIC_TYPES = {name: kind for name, kind, _ in DAILY_BASIC_COLUMN_SPECS}


class DailyBasicValidationError(ValueError):
    """An invalid source or candidate must never be promoted."""


def daily_basic_trade_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise DailyBasicValidationError("trade_date 必须是 YYYY-MM-DD")
    if value < DAILY_BASIC_HISTORY_START:
        raise DailyBasicValidationError("before_history_start：早于每日指标历史起点")
    return value


def daily_basic_code_hash(codes) -> str:
    return sha256("\n".join(sorted(set(codes))).encode()).hexdigest()


def daily_basic_request_policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=1,
        max_requests=12,
        max_elapsed_seconds=60,
        max_retries=3,
    )
