"""Approved daily-basic identity, decimal and request contracts."""

import re
from datetime import date, time
from hashlib import sha256

from orchestrator.defs.tushare_request_policy import TushareRequestPolicy
from orchestrator.tushare_download.download_models import DownloadMode
from orchestrator.tushare_download.source_contract import (
    ModeRule,
    OrderingRule,
    PaginationRule,
    ParameterRule,
    SourceDatasetContract,
    SourceField,
    SourceKind,
    TimeRule,
)

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
    ("limit_status", "INTEGER", "收盘涨跌状态，0～6；允许源端为空"),
)
DAILY_BASIC_FIELDS = tuple(item[0] for item in DAILY_BASIC_COLUMN_SPECS)
DAILY_BASIC_TYPES = {name: kind for name, kind, _ in DAILY_BASIC_COLUMN_SPECS}
DAILY_BASIC_DECIMAL_FIELDS = tuple(
    name for name, kind, _ in DAILY_BASIC_COLUMN_SPECS if kind.startswith("DECIMAL(")
)
DAILY_BASIC_B_SHARE_PATTERN = r"(?:20[0-9]{4}[.]SZ|900[0-9]{3}[.]SH)"
DAILY_BASIC_SOURCE_CONTRACT = SourceDatasetContract(
    contract_name="daily_basic",
    dataset_id="daily_basic",
    version="1",
    source_api_name="daily_basic",
    fields=tuple(
        SourceField(
            name,
            SourceKind.STRING if kind == "VARCHAR" else
            SourceKind.INTEGER if kind == "INTEGER" else SourceKind.NUMBER,
            format="YYYYMMDD" if name == "trade_date" else "",
            description=description,
            nullable=name not in ("ts_code", "trade_date"),
        )
        for name, kind, description in DAILY_BASIC_COLUMN_SPECS
    ),
    parameters=tuple(
        ParameterRule(name, SourceKind.STRING)
        for name in ("ts_code", "trade_date", "start_date", "end_date")
    ),
    modes=(ModeRule(DownloadMode.BY_POINT, point_param="trade_date"),),
    pagination=PaginationRule(
        strategy=2, effective_limit=DAILY_BASIC_PAGE_SIZE,
        offset_start=0, offset_step=DAILY_BASIC_PAGE_SIZE,
        limit_param="limit", offset_param="offset",
    ),
    time_rules=(TimeRule("day", "1", "YYYY-MM-DD", "YYYYMMDD", "trade_date"),),
    ordering=OrderingRule("trade_date", "day"),
    source_evidence=(
        "https://tushare.pro/document/2?doc_id=32",
        "2026-11-12单代码、单日期实测完整19字段；limit_status显式请求。",
    ),
    local_evidence_paths=(
        "docs/sources/tushare/股票数据/行情数据/0032_每日指标.md",
        "docs/datasets/daily-basic-limit-status-expansion-plan-and-low-level-design-v1.md",
    ),
)


class DailyBasicValidationError(ValueError):
    """An invalid source or candidate must never be promoted."""


def daily_basic_is_b_share(code: str) -> bool:
    return re.fullmatch(DAILY_BASIC_B_SHARE_PATTERN, code) is not None


def validate_daily_basic_limit_status(value, code, trade_date, *, required=False):
    if value is None and not required:
        return
    if type(value) is not int or not 0 <= value <= 6:
        raise DailyBasicValidationError(
            f"limit_status：日期={trade_date} 代码={code} 名称=缺失 "
            f"字段=limit_status 原值={value!r} 类型={type(value).__name__}；"
            + ("应有股票的状态不得为空" if value is None else "必须为原生整数0～6")
        )


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
