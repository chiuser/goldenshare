"""Stable source and execution contracts for Tushare ``idx_factor_pro``."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from orchestrator.seeds.market.major_indices import (
    active_major_indices_seed_rows,
    load_major_indices_seed,
)

IDX_FACTOR_PRO_API_NAME = "idx_factor_pro"
IDX_FACTOR_PRO_PAGE_LIMIT = 8_000
IDX_FACTOR_PRO_RAW_ASSET_KEY = "raw_tushare_idx_factor_pro"
IDX_FACTOR_PRO_SILVER_ASSET_KEY = "silver_index_factor_pro"
IDX_FACTOR_PRO_RAW_JOB_NAME = "raw_tushare_idx_factor_pro_update_job"
IDX_FACTOR_PRO_SILVER_JOB_NAME = "silver_index_factor_pro_update_job"
IDX_FACTOR_PRO_RAW_SENSOR_NAME = f"{IDX_FACTOR_PRO_RAW_JOB_NAME}_sensor"
IDX_FACTOR_PRO_SILVER_SENSOR_NAME = f"{IDX_FACTOR_PRO_SILVER_JOB_NAME}_sensor"
IDX_FACTOR_PRO_PARTITION_SENSOR_NAME = "idx_factor_pro_trade_day_sensor"
IDX_FACTOR_PRO_AUTOMATION_CONTRACT_REVISION = "v1"

IDX_FACTOR_PRO_SOURCE_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_change",
    "vol",
    "amount",
    "asi_bfq",
    "asit_bfq",
    "atr_bfq",
    "bbi_bfq",
    "bias1_bfq",
    "bias2_bfq",
    "bias3_bfq",
    "boll_lower_bfq",
    "boll_mid_bfq",
    "boll_upper_bfq",
    "brar_ar_bfq",
    "brar_br_bfq",
    "cci_bfq",
    "cr_bfq",
    "dfma_dif_bfq",
    "dfma_difma_bfq",
    "dmi_adx_bfq",
    "dmi_adxr_bfq",
    "dmi_mdi_bfq",
    "dmi_pdi_bfq",
    "downdays",
    "updays",
    "dpo_bfq",
    "madpo_bfq",
    "ema_bfq_10",
    "ema_bfq_20",
    "ema_bfq_250",
    "ema_bfq_30",
    "ema_bfq_5",
    "ema_bfq_60",
    "ema_bfq_90",
    "emv_bfq",
    "maemv_bfq",
    "expma_12_bfq",
    "expma_50_bfq",
    "kdj_bfq",
    "kdj_d_bfq",
    "kdj_k_bfq",
    "ktn_down_bfq",
    "ktn_mid_bfq",
    "ktn_upper_bfq",
    "lowdays",
    "topdays",
    "ma_bfq_10",
    "ma_bfq_20",
    "ma_bfq_250",
    "ma_bfq_30",
    "ma_bfq_5",
    "ma_bfq_60",
    "ma_bfq_90",
    "macd_bfq",
    "macd_dea_bfq",
    "macd_dif_bfq",
    "mass_bfq",
    "ma_mass_bfq",
    "mfi_bfq",
    "mtm_bfq",
    "mtmma_bfq",
    "obv_bfq",
    "psy_bfq",
    "psyma_bfq",
    "roc_bfq",
    "maroc_bfq",
    "rsi_bfq_12",
    "rsi_bfq_24",
    "rsi_bfq_6",
    "taq_down_bfq",
    "taq_mid_bfq",
    "taq_up_bfq",
    "trix_bfq",
    "trma_bfq",
    "vr_bfq",
    "wr_bfq",
    "wr1_bfq",
    "xsii_td1_bfq",
    "xsii_td2_bfq",
    "xsii_td3_bfq",
    "xsii_td4_bfq",
)

IDX_FACTOR_PRO_RAW_COLUMN_TYPES = MappingProxyType(
    {
        column: "VARCHAR" if column in {"ts_code", "trade_date"} else "DOUBLE"
        for column in IDX_FACTOR_PRO_SOURCE_COLUMNS
    }
)
IDX_FACTOR_PRO_SILVER_COLUMN_TYPES = MappingProxyType(
    {**IDX_FACTOR_PRO_RAW_COLUMN_TYPES, "trade_date": "DATE"}
)

IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES = MappingProxyType(
    {
        "000001.SH": "1990-12-19",
        "399001.SZ": "1991-04-03",
        "399006.SZ": "2010-06-01",
        "000688.SH": "2019-12-31",
        "000300.SH": "2005-01-04",
        "000905.SH": "2005-01-04",
        "000852.SH": "2005-01-04",
        "899050.BJ": "2022-12-19",
        "000510.SH": "2024-09-23",
        "000016.SH": "2004-01-02",
        "000680.SH": "2025-01-17",
    }
)

IDX_FACTOR_PRO_RAW_CHECKS = (
    "raw_tushare_idx_factor_pro_contract_check",
    "raw_tushare_idx_factor_pro_partition_scope_check",
    "raw_tushare_idx_factor_pro_key_integrity_check",
    "raw_tushare_idx_factor_pro_selection_parity_check",
)
IDX_FACTOR_PRO_RAW_NULLABLE_CHECK = (
    "raw_tushare_idx_factor_pro_nullable_drift_check"
)
IDX_FACTOR_PRO_SILVER_CHECKS = (
    "silver_index_factor_pro_contract_check",
    "silver_index_factor_pro_source_parity_check",
    "silver_index_factor_pro_cast_integrity_check",
)


class IdxFactorProContractError(ValueError):
    """Raised when an idx_factor_pro request violates the frozen contract."""


@dataclass(frozen=True, slots=True)
class IdxFactorProRequest:
    api_name: str
    params: Mapping[str, object]
    fields: tuple[str, ...]


def normalize_idx_factor_pro_trade_date(value: str | date) -> str:
    """Return one strict ISO trade date used by partitions and path builders."""

    if isinstance(value, datetime):
        raise IdxFactorProContractError("trade date must not include a time component")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise IdxFactorProContractError(
            f"idx_factor_pro trade date must use YYYY-MM-DD: {value!r}"
        ) from exc
    if text != parsed.isoformat():
        raise IdxFactorProContractError(
            f"idx_factor_pro trade date must use YYYY-MM-DD: {value!r}"
        )
    return text


def approved_idx_factor_pro_daily_codes() -> tuple[str, ...]:
    """Return the current daily major-index seed after coverage fail-closed checks."""

    codes = tuple(row.ts_code for row in load_major_indices_seed())
    if set(codes) != set(IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES):
        raise IdxFactorProContractError(
            "idx_factor_pro coverage keys must exactly match the daily major-index seed"
        )
    return codes


def active_idx_factor_pro_daily_codes(trade_date: str | date) -> tuple[str, ...]:
    """Return the date-effective daily seed without consulting minute scope."""

    normalized_date = normalize_idx_factor_pro_trade_date(trade_date)
    approved_codes = set(approved_idx_factor_pro_daily_codes())
    return tuple(
        row.ts_code
        for row in active_major_indices_seed_rows(normalized_date)
        if row.ts_code in approved_codes
    )


def _validated_offset(offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise IdxFactorProContractError("idx_factor_pro offset must be an integer")
    if offset < 0 or offset % IDX_FACTOR_PRO_PAGE_LIMIT != 0:
        raise IdxFactorProContractError(
            "idx_factor_pro offset must be a non-negative multiple of 8000"
        )
    return offset


def build_idx_factor_pro_daily_request(
    partition_key: str | date,
    offset: int,
) -> IdxFactorProRequest:
    trade_date = normalize_idx_factor_pro_trade_date(partition_key)
    return IdxFactorProRequest(
        api_name=IDX_FACTOR_PRO_API_NAME,
        params=MappingProxyType(
            {
                "trade_date": trade_date.replace("-", ""),
                "limit": IDX_FACTOR_PRO_PAGE_LIMIT,
                "offset": _validated_offset(offset),
            }
        ),
        fields=IDX_FACTOR_PRO_SOURCE_COLUMNS,
    )


def build_idx_factor_pro_history_request(
    ts_code: str,
    start_date: str | date,
    end_date: str | date,
    offset: int,
) -> IdxFactorProRequest:
    normalized_code = str(ts_code).strip().upper()
    approved_codes = approved_idx_factor_pro_daily_codes()
    if normalized_code not in approved_codes:
        raise IdxFactorProContractError(
            f"idx_factor_pro history code is outside the daily seed: {ts_code!r}"
        )
    normalized_start = normalize_idx_factor_pro_trade_date(start_date)
    expected_start = IDX_FACTOR_PRO_FIRST_AVAILABLE_TRADE_DATES[normalized_code]
    if normalized_start != expected_start:
        raise IdxFactorProContractError(
            "idx_factor_pro history start must equal the frozen first available date: "
            f"code={normalized_code}, expected={expected_start}, got={normalized_start}"
        )
    normalized_end = normalize_idx_factor_pro_trade_date(end_date)
    if normalized_end < normalized_start:
        raise IdxFactorProContractError(
            "idx_factor_pro history end date precedes its frozen start date"
        )
    return IdxFactorProRequest(
        api_name=IDX_FACTOR_PRO_API_NAME,
        params=MappingProxyType(
            {
                "ts_code": normalized_code,
                "start_date": normalized_start.replace("-", ""),
                "end_date": normalized_end.replace("-", ""),
                "limit": IDX_FACTOR_PRO_PAGE_LIMIT,
                "offset": _validated_offset(offset),
            }
        ),
        fields=IDX_FACTOR_PRO_SOURCE_COLUMNS,
    )
