"""Stable contracts for major-index minute technical and state assets."""

from datetime import date

from orchestrator.defs.run_contracts.major_index_mins import (
    effective_silver_codes_for_date,
    major_index_mins_source_scope,
    normalize_major_index_mins_trade_date,
)

MAJOR_INDEX_MINS_TECHNICAL_FREQS = (1, 5, 15, 30, 60, 90, 120)
MAJOR_INDEX_MINS_TECHNICAL_DATASET_ID = "major_index_mins_technical"
MAJOR_INDEX_MINS_TECHNICAL_STATE_DATASET_ID = "major_index_mins_technical_state"
MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME = (
    "gold_major_index_mins_technical_daily_update_job"
)
MAJOR_INDEX_MINS_TECHNICAL_SENSOR_NAME = (
    f"{MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME}_sensor"
)
MAJOR_INDEX_MINS_TECHNICAL_AUTOMATION_CONTRACT_REVISION = "v1"

MA_PERIODS = (5, 10, 20, 30, 60, 90, 250)
BOLL_PERIOD = 20
BOLL_STD_MULTIPLIER = 2.0
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
KDJ_PERIOD = 9
KDJ_ALPHA = 1.0 / 3.0
PARAMS_KEY = (
    "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3"
)
INDICATOR_VERSION = 1

GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_SPECS = (
    ("ts_code", "VARCHAR", "主要指数代码，不得为空"),
    ("freq", "SMALLINT", "分钟频率，固定为 1、5、15、30、60、90 或 120，不得为空"),
    ("trade_date", "DATE", "交易日，不得为空"),
    ("trade_time", "TIMESTAMP", "分钟 bar 时间，不得为空"),
    ("ma_5", "DOUBLE", "MA5；warm-up 未满足时允许为空"),
    ("ma_10", "DOUBLE", "MA10；warm-up 未满足时允许为空"),
    ("ma_20", "DOUBLE", "MA20；warm-up 未满足时允许为空"),
    ("ma_30", "DOUBLE", "MA30；warm-up 未满足时允许为空"),
    ("ma_60", "DOUBLE", "MA60；warm-up 未满足时允许为空"),
    ("ma_90", "DOUBLE", "MA90；warm-up 未满足时允许为空"),
    ("ma_250", "DOUBLE", "MA250；warm-up 未满足时允许为空"),
    ("boll_mid", "DOUBLE", "BOLL 中轨；warm-up 未满足时允许为空"),
    ("boll_upper", "DOUBLE", "BOLL 上轨；warm-up 未满足时允许为空"),
    ("boll_lower", "DOUBLE", "BOLL 下轨；warm-up 未满足时允许为空"),
    ("macd_dif", "DOUBLE", "MACD DIF 递推值，不得为空"),
    ("macd_dea", "DOUBLE", "MACD DEA 递推值，不得为空"),
    ("macd", "DOUBLE", "MACD 柱值，不得为空"),
    ("kdj_k", "DOUBLE", "KDJ K 递推值，不得为空"),
    ("kdj_d", "DOUBLE", "KDJ D 递推值，不得为空"),
    ("kdj_j", "DOUBLE", "KDJ J 值，不得为空"),
    ("observation_count", "INTEGER", "该代码该频率累计有效观察数，不得为空"),
    ("params_key", "VARCHAR", "技术指标参数合同标识，不得为空"),
    ("indicator_version", "INTEGER", "技术指标合同版本，不得为空"),
)

GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_SPECS = (
    ("ts_code", "VARCHAR", "主要指数代码，不得为空"),
    ("freq", "SMALLINT", "分钟频率，固定为 1、5、15、30、60、90 或 120，不得为空"),
    ("trade_date", "DATE", "状态所属交易日，不得为空"),
    ("last_trade_time", "TIMESTAMP", "当日最后一根有效分钟 bar 时间，不得为空"),
    ("macd_ema_fast", "DOUBLE", "MACD 快线 EMA 前态，不得为空"),
    ("macd_ema_slow", "DOUBLE", "MACD 慢线 EMA 前态，不得为空"),
    ("macd_dea", "DOUBLE", "MACD DEA 前态，不得为空"),
    ("kdj_k", "DOUBLE", "KDJ K 前态，不得为空"),
    ("kdj_d", "DOUBLE", "KDJ D 前态，不得为空"),
    ("params_key", "VARCHAR", "技术指标参数合同标识，不得为空"),
    ("indicator_version", "INTEGER", "技术指标合同版本，不得为空"),
)

GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMNS = tuple(
    name for name, _type, _description in GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_SPECS
)
GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_TYPES = {
    name: type_name
    for name, type_name, _description in GOLD_MAJOR_INDEX_MINS_TECHNICAL_COLUMN_SPECS
}
GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMNS = tuple(
    name
    for name, _type, _description in GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_SPECS
)
GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_TYPES = {
    name: type_name
    for name, type_name, _description in GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_COLUMN_SPECS
}


class MajorIndexMinsTechnicalContractError(ValueError):
    """Raised when a technical frequency or asset identity is unsupported."""


def normalize_major_index_mins_technical_freq(value: object) -> int:
    if isinstance(value, bool):
        raise MajorIndexMinsTechnicalContractError(
            "major-index technical frequency must be an integer"
        )
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MajorIndexMinsTechnicalContractError(
            f"unsupported major-index technical frequency: {value!r}"
        ) from exc
    if str(value).strip() != str(normalized) or normalized not in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        raise MajorIndexMinsTechnicalContractError(
            f"unsupported major-index technical frequency: {value!r}"
        )
    return normalized


def major_index_mins_technical_asset_key(freq: object) -> str:
    return f"gold_major_index_mins_technical_{normalize_major_index_mins_technical_freq(freq)}m"


def major_index_mins_technical_state_asset_key(freq: object) -> str:
    return (
        "gold_major_index_mins_technical_state_"
        f"{normalize_major_index_mins_technical_freq(freq)}m"
    )


def major_index_mins_technical_checks(freq: object) -> tuple[str, ...]:
    asset_key = major_index_mins_technical_asset_key(freq)
    return (
        f"{asset_key}_contract_check",
        f"{asset_key}_source_coverage_check",
        f"{asset_key}_partition_frequency_check",
        f"{asset_key}_key_integrity_check",
        f"{asset_key}_warmup_and_finite_check",
        f"{asset_key}_no_future_input_check",
    )


def major_index_mins_technical_state_checks(freq: object) -> tuple[str, ...]:
    asset_key = major_index_mins_technical_state_asset_key(freq)
    return (
        f"{asset_key}_contract_check",
        f"{asset_key}_coverage_check",
        f"{asset_key}_last_trade_time_check",
        f"{asset_key}_continuity_check",
    )


def expected_major_index_mins_technical_codes(
    trade_date: str | date,
) -> tuple[str, ...]:
    """Use the minute Silver scope directly; never read the daily seed here."""

    return effective_silver_codes_for_date(trade_date)


def major_index_mins_technical_seed_codes(
    trade_date: str | date,
) -> tuple[str, ...]:
    """Return codes on their published first available Silver trade date."""

    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    return tuple(
        code
        for code in expected_major_index_mins_technical_codes(normalized_date)
        if major_index_mins_source_scope(code).source_start_date
        == normalized_date
    )


def major_index_mins_technical_continuing_codes(
    trade_date: str | date,
) -> tuple[str, ...]:
    """Return codes that must inherit exact previous-date recursive state."""

    current_codes = set(expected_major_index_mins_technical_codes(trade_date))
    seed_codes = set(major_index_mins_technical_seed_codes(trade_date))
    return tuple(sorted(current_codes - seed_codes))
