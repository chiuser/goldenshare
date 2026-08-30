from __future__ import annotations

import importlib
import pkgutil
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

import orchestrator.defs.checks as checks_pkg
import orchestrator.defs.sensors as sensors_pkg
from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
)
from orchestrator.defs.catalog import list_lake_asset_catalog_entries
from orchestrator.defs.run_contracts.etf_basic import (
    RAW_ETF_BASIC_CHECKS,
    SILVER_ETF_BASIC_CHECKS,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_GOLD_CHECKS,
    INDEX_MINS_RAW_CHECKS,
    INDEX_MINS_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_GOLD_CHECKS,
    MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
    MAJOR_INDEX_MINS_RAW_CHECKS,
    MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
    MAJOR_INDEX_MINS_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)
from orchestrator.defs.sensors.readiness import AssetReadinessSpec

DEFS_DIR = Path("src/orchestrator/defs")
JOBS_DIR = DEFS_DIR / "jobs"

KEEP_BLOCKING_DAGSTER = "KEEP_BLOCKING_DAGSTER"
MERGE_BLOCKING_DAGSTER = "MERGE_BLOCKING_DAGSTER"
MOVE_TO_SENSOR_LAKE_READINESS = "MOVE_TO_SENSOR_LAKE_READINESS"
MOVE_TO_METADATA = "MOVE_TO_METADATA"
MOVE_TO_OFFLINE_AUDIT = "MOVE_TO_OFFLINE_AUDIT"
RETENTION_ONLY = "RETENTION_ONLY"

GOVERNANCE_CATEGORIES = {
    KEEP_BLOCKING_DAGSTER,
    MERGE_BLOCKING_DAGSTER,
    MOVE_TO_SENSOR_LAKE_READINESS,
    MOVE_TO_METADATA,
    MOVE_TO_OFFLINE_AUDIT,
    RETENTION_ONLY,
}


@dataclass(frozen=True)
class AssetCheckGovernanceRule:
    category: str
    participates_in_sensor_readiness: bool
    retention_allowed: bool
    implementation_phase: str
    protected_reason: str | None = None


def _rule(
    *,
    category: str,
    phase: str,
    readiness: bool = False,
    retention_allowed: bool = True,
    protected_reason: str | None = None,
) -> AssetCheckGovernanceRule:
    return AssetCheckGovernanceRule(
        category=category,
        participates_in_sensor_readiness=readiness,
        retention_allowed=retention_allowed,
        implementation_phase=phase,
        protected_reason=protected_reason,
    )


def _rules(
    check_names: tuple[str, ...],
    *,
    category: str,
    phase: str,
    readiness: bool = False,
    retention_allowed: bool = True,
) -> dict[str, AssetCheckGovernanceRule]:
    return {
        check_name: _rule(
            category=category,
            phase=phase,
            readiness=readiness,
            retention_allowed=retention_allowed,
        )
        for check_name in check_names
    }


RAW_TRADE_CALENDAR_CHECKS = (
    "raw_trade_calendar_contract_check",
)
SILVER_TRADE_CALENDAR_CHECKS = (
    "silver_trade_calendar_required_columns_non_null",
    "silver_trade_calendar_unique_exchange_trade_date",
)
RAW_STOCK_BASIC_CHECKS = (
    "raw_stock_basic_contract_check",
    "raw_stock_basic_key_integrity_check",
)
SILVER_STOCK_BASIC_CHECKS = (
    "silver_stock_basic_contract_check",
    "silver_stock_basic_key_integrity_check",
    "silver_stock_basic_current_listed_domain_check",
)
SILVER_STOCK_LIFECYCLE_CHECKS = (
    "silver_stock_lifecycle_contract_check",
    "silver_stock_lifecycle_key_integrity_check",
    "silver_stock_lifecycle_domain_check",
)
RAW_NAMECHANGE_CHECKS = (
    "raw_namechange_contract_check",
    "raw_namechange_key_integrity_check",
    "raw_namechange_date_domain_check",
)
SILVER_NAMECHANGE_CHECKS = (
    "silver_namechange_contract_check",
    "silver_namechange_key_integrity_check",
    "silver_namechange_interval_domain_check",
)
SILVER_STOCK_IDENTITY_MAP_CHECKS = (
    "silver_stock_identity_map_contract_check",
    "silver_stock_identity_map_key_integrity_check",
    "silver_stock_identity_map_reference_domain_check",
)
SILVER_DC_INDUSTRY_HIERARCHY_CHECKS = (
    "silver_dc_industry_hierarchy_core_check",
)
RAW_SUSPEND_D_CHECKS = (
    "raw_suspend_d_contract_check",
    "raw_suspend_d_partition_allowed_check",
)
SILVER_SUSPEND_D_CHECKS = (
    "silver_suspend_d_key_integrity_check",
    "silver_suspend_d_suspend_type_domain_check",
    "silver_suspend_d_partition_allowed_check",
)
RAW_STOCK_DAILY_CHECKS = (
    "raw_stock_daily_contract_check",
    "raw_stock_daily_key_integrity_check",
    "raw_stock_daily_tradable_universe_check",
    "raw_stock_daily_partition_allowed_check",
)
RAW_STK_NINETURN_CHECKS = (
    "raw_tushare_stk_nineturn_contract_check",
    "raw_tushare_stk_nineturn_content_integrity_check",
)
SILVER_STOCK_NINETURN_DAILY_CHECKS = (
    "silver_stock_nineturn_daily_contract_check",
    "silver_stock_nineturn_daily_canonical_integrity_check",
)
SILVER_STOCK_DAILY_CHECKS = (
    "silver_stock_daily_contract_check",
    "silver_stock_daily_key_integrity_check",
    "silver_stock_daily_value_domain_check",
    "silver_stock_daily_lifecycle_coverage_check",
    "silver_stock_daily_tradable_universe_check",
    "silver_stock_daily_partition_allowed_check",
)
RAW_ADJ_FACTOR_CHECKS = (
    "raw_adj_factor_contract_check",
    "raw_adj_factor_key_value_integrity_check",
    "raw_adj_factor_partition_allowed_check",
)
SILVER_ADJ_FACTOR_CHECKS = (
    "silver_adj_factor_contract_check",
    "silver_adj_factor_key_value_integrity_check",
    "silver_adj_factor_lifecycle_coverage_check",
    "silver_adj_factor_partition_allowed_check",
)
RAW_STK_MINS_CHECKS = (
    "raw_stk_mins_contract_check",
    "raw_stk_mins_key_integrity_check",
    "raw_stk_mins_value_domain_check",
)
SILVER_STK_MINS_CHECKS = (
    "silver_stk_mins_contract_check",
    "silver_stk_mins_key_integrity_check",
    "silver_stk_mins_reference_coverage_check",
    "silver_stk_mins_value_domain_check",
)
GOLD_STK_MINS_QFQ_NATIVE_CHECKS = (
    "gold_stk_mins_qfq_contract_check",
    "gold_stk_mins_qfq_key_integrity_check",
    "gold_stk_mins_qfq_value_domain_check",
    "gold_stk_mins_qfq_source_coverage_check",
)
GOLD_STK_MINS_QFQ_DERIVED_CHECKS = (
    "gold_stk_mins_qfq_derived_source_coverage_check",
    "gold_stk_mins_qfq_contract_check",
    "gold_stk_mins_qfq_key_integrity_check",
    "gold_stk_mins_qfq_value_domain_check",
)
MACD_KDJ_INDICATOR_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_contract_check",
    "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
)
MACD_KDJ_STATE_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check",
    "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check",
)
RAW_INDEX_BASIC_CHECKS = (
    "raw_index_basic_contract_check",
    "raw_index_basic_key_integrity_check",
    "raw_index_basic_date_domain_check",
)
SILVER_INDEX_BASIC_CHECKS = (
    "silver_index_basic_contract_check",
    "silver_index_basic_key_integrity_check",
    "silver_index_basic_lifecycle_domain_check",
)
RAW_INDEX_DAILY_CHECKS = (
    "raw_index_daily_code_coverage_check",
    "raw_index_daily_file_contract_check",
)
SILVER_INDEX_DAILY_CHECKS = (
    "silver_index_daily_contract_check",
    "silver_index_daily_key_integrity_check",
    "silver_index_daily_value_domain_check",
    "silver_index_daily_registered_code_coverage_check",
)
GOLD_MARKET_MAJOR_INDICES_CHECKS = (
    "gold_market_major_indices_daily_contract_check",
    "gold_market_major_indices_daily_value_domain_check",
    "gold_market_major_indices_daily_seed_coverage_check",
    "gold_market_major_indices_daily_ranking_consistency_check",
)
GOLD_MARKET_BREADTH_CHECKS = (
    "gold_market_breadth_contract_check",
    "gold_market_breadth_value_domain_check",
    "gold_market_breadth_silver_reconciliation_check",
    "gold_market_breadth_partition_allowed_check",
)
GOLD_STOCK_RETURN_DISTRIBUTION_CHECKS = (
    "gold_stock_return_distribution_contract_check",
    "gold_stock_return_distribution_value_domain_check",
    "gold_stock_return_distribution_silver_reconciliation_check",
    "gold_stock_return_distribution_partition_allowed_check",
)
CH_MARKET_BREADTH_CHECKS = (
    "ch_share_fact_market_breadth_contract_check",
    "ch_share_fact_market_breadth_gold_reconciliation_check",
)
PROD_CH_MARKET_BREADTH_CHECKS = (
    "prod_ch_share_fact_market_breadth_date_matches_partition",
    "prod_ch_share_fact_market_breadth_row_count_is_one",
    "prod_ch_share_fact_market_breadth_row_matches_local",
    "prod_ch_share_fact_market_breadth_updated_at_not_older_than_local",
)
LAKE_ROOT_HEALTH_CHECKS = (
    "lake_root_health_ready",
)
RAW_DC_BOARD_CHECKS = (
    "raw_tushare_dc_index_core_check",
    "raw_tushare_dc_member_core_check",
    "raw_tushare_dc_daily_core_check",
)
SILVER_DC_BOARD_CHECKS = (
    "silver_dc_index_core_check",
    "silver_dc_member_core_check",
    "silver_dc_daily_core_check",
)
INDEX_GLOBAL_RAW_CHECKS = (
    "raw_index_global_core_check",
)
INDEX_GLOBAL_SILVER_CHECKS = (
    "silver_index_global_core_check",
)


def _index_mins_asset_rules() -> dict[str, dict[str, AssetCheckGovernanceRule]]:
    rules: dict[str, dict[str, AssetCheckGovernanceRule]] = {}
    for frequency, check_name in zip(
        (1, 5, 15, 30, 60), INDEX_MINS_RAW_CHECKS, strict=True
    ):
        rules[f"raw_index_mins_{frequency}m"] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="INDEX_MINS_P5",
            readiness=False,
            retention_allowed=True,
        )
    for frequency, check_name in zip(
        (1, 5, 15, 30, 60, 90, 120), INDEX_MINS_SILVER_CHECKS, strict=True
    ):
        rules[f"silver_index_mins_{frequency}m"] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="INDEX_MINS_P5",
            readiness=False,
            retention_allowed=True,
        )
    for frequency, check_name in zip(
        (1, 5, 15, 30, 60, 90, 120), INDEX_MINS_GOLD_CHECKS, strict=True
    ):
        rules[f"gold_index_mins_{frequency}m"] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="CN_A_MINUTE_GOLD_P2",
            readiness=False,
            retention_allowed=True,
        )
    return rules


def _major_index_mins_asset_rules() -> dict[
    str, dict[str, AssetCheckGovernanceRule]
]:
    rules: dict[str, dict[str, AssetCheckGovernanceRule]] = {}
    nineturn_upstream_asset_keys = frozenset(MAJOR_INDEX_MINS_GOLD_ASSET_KEYS[1:])
    for asset_key, check_name in zip(
        MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
        MAJOR_INDEX_MINS_RAW_CHECKS,
        strict=True,
    ):
        rules[asset_key] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="MAJOR_INDEX_MINS_P5",
            readiness=False,
            retention_allowed=True,
        )
    for asset_key, check_name in zip(
        MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
        MAJOR_INDEX_MINS_SILVER_CHECKS,
        strict=True,
    ):
        rules[asset_key] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="MAJOR_INDEX_MINS_P5",
            readiness=False,
            retention_allowed=True,
        )
    for asset_key, check_name in zip(
        MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
        MAJOR_INDEX_MINS_GOLD_CHECKS,
        strict=True,
    ):
        rules[asset_key] = _rules(
            (check_name,),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="CN_A_MINUTE_GOLD_P2",
            readiness=asset_key in nineturn_upstream_asset_keys,
            retention_allowed=True,
        )
    return rules


GOLD_STOCK_DAILY_QFQ_CHECKS = (
    "gold_stock_daily_qfq_contract_check",
)
GOLD_DC_DAILY_TECHNICAL_CHECKS = (
    "gold_dc_daily_technical_core_check",
)
GOLD_STOCK_DAILY_QFQ_NINETURN_CHECKS = (
    "gold_stock_daily_qfq_nineturn_integrity_check",
)
GOLD_MAJOR_INDEX_DAILY_NINETURN_CHECKS = (
    "gold_major_index_daily_nineturn_integrity_check",
)
GOLD_MAJOR_INDEX_MINS_NINETURN_CHECKS_BY_FREQ = {
    freq: (f"gold_major_index_mins_nineturn_{freq}m_integrity_check",)
    for freq in (5, 15, 30, 60, 90, 120)
}
GOLD_STK_MINS_QFQ_NINETURN_CHECKS_BY_FREQ = {
    freq: (f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check",)
    for freq in (30, 60, 90, 120)
}
PROD_CORE_INDEX_DAILY_NINETURN_CHECKS = (
    "prod_core_index_daily_nineturn_partition_check",
)
PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECKS = (
    "prod_core_stock_daily_qfq_nineturn_partition_check",
)
PROD_CH_DC_DAILY_TECHNICAL_CHECKS = (
    "prod_ch_dc_daily_technical_core_check",
)

PLANNED_CATALOG_ASSET_KEYS = {
    "silver_etf_basic",
    *(f"raw_etf_mins_{freq}m" for freq in ETF_MINS_ASSET_FREQS),
    *(f"silver_etf_mins_{freq}m" for freq in ETF_MINS_ASSET_FREQS),
    *(
        major_index_mins_technical_asset_key(freq)
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    ),
    *(
        major_index_mins_technical_state_asset_key(freq)
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    ),
}


def _planned_etf_asset_rules() -> dict[
    str, dict[str, AssetCheckGovernanceRule]
]:
    rules = {
        "raw_tushare_etf_basic": _rules(
            RAW_ETF_BASIC_CHECKS,
            category=KEEP_BLOCKING_DAGSTER,
            phase="ETF_BASIC_RAW",
            readiness=False,
            retention_allowed=True,
        ),
        "silver_etf_basic": _rules(
            SILVER_ETF_BASIC_CHECKS,
            category=KEEP_BLOCKING_DAGSTER,
            phase="ETF_BASIC_SILVER",
            readiness=False,
            retention_allowed=True,
        ),
    }
    for freq in ETF_MINS_ASSET_FREQS:
        rules[f"raw_etf_mins_{freq}m"] = _rules(
            raw_etf_mins_check_names(freq),
            category=KEEP_BLOCKING_DAGSTER,
            phase="ETF_MINS_RAW",
            readiness=False,
            retention_allowed=True,
        )
        rules[f"silver_etf_mins_{freq}m"] = _rules(
            silver_etf_mins_check_names(freq),
            category=KEEP_BLOCKING_DAGSTER,
            phase="ETF_MINS_SILVER",
            readiness=False,
            retention_allowed=True,
        )
    return rules


def _planned_index_technical_asset_rules() -> dict[
    str, dict[str, AssetCheckGovernanceRule]
]:
    rules = {
        "silver_index_factor_pro": _rules(
            IDX_FACTOR_PRO_SILVER_CHECKS,
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="IDX_FACTOR_PRO_M3",
            readiness=False,
            retention_allowed=True,
        )
    }
    for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS:
        technical_key = major_index_mins_technical_asset_key(freq)
        rules[technical_key] = _rules(
            major_index_mins_technical_checks(freq),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="MAJOR_INDEX_TECHNICAL_M4",
            readiness=False,
            retention_allowed=True,
        )
        state_key = major_index_mins_technical_state_asset_key(freq)
        rules[state_key] = _rules(
            major_index_mins_technical_state_checks(freq),
            category=MOVE_TO_SENSOR_LAKE_READINESS,
            phase="MAJOR_INDEX_TECHNICAL_M4",
            readiness=False,
            retention_allowed=True,
        )
    return rules


def _stk_mins_asset_rules() -> dict[str, dict[str, AssetCheckGovernanceRule]]:
    freqs = (1, 5, 15, 30, 60)
    gold_freqs = (1, 5, 15, 30, 60, 90, 120)
    rules: dict[str, dict[str, AssetCheckGovernanceRule]] = {}
    for freq in freqs:
        rules[f"raw_stk_mins_{freq}m"] = _rules(
            RAW_STK_MINS_CHECKS,
            category=RETENTION_ONLY,
            phase="P6",
            readiness=True,
            retention_allowed=True,
        )
        rules[f"silver_stk_mins_{freq}m"] = _rules(
            SILVER_STK_MINS_CHECKS,
            category=RETENTION_ONLY,
            phase="P6",
            readiness=True,
            retention_allowed=True,
        )
    for freq in gold_freqs:
        qfq_checks = (
            GOLD_STK_MINS_QFQ_NATIVE_CHECKS
            if freq in freqs
            else GOLD_STK_MINS_QFQ_DERIVED_CHECKS
        )
        rules[f"gold_stk_mins_qfq_{freq}m"] = _rules(
            qfq_checks,
            category=RETENTION_ONLY,
            phase="P6",
            readiness=True,
            retention_allowed=True,
        )
        rules[f"gold_stk_mins_qfq_macd_kdj_{freq}m"] = _rules(
            MACD_KDJ_INDICATOR_CHECKS,
            category=RETENTION_ONLY,
            phase="P6",
            readiness=True,
            retention_allowed=True,
        )
        rules[f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"] = _rules(
            MACD_KDJ_STATE_CHECKS,
            category=RETENTION_ONLY,
            phase="P6",
            readiness=True,
            retention_allowed=True,
        )
    return rules


ASSET_CHECK_GOVERNANCE: dict[str, dict[str, AssetCheckGovernanceRule]] = {
    "raw_tushare_trade_calendar": _rules(
        RAW_TRADE_CALENDAR_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        retention_allowed=True,
    ),
    "silver_trade_calendar": _rules(
        SILVER_TRADE_CALENDAR_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        retention_allowed=True,
    ),
    "raw_tushare_stock_basic": _rules(
        RAW_STOCK_BASIC_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_stock_basic": _rules(
        SILVER_STOCK_BASIC_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_stock_lifecycle": _rules(
        SILVER_STOCK_LIFECYCLE_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "raw_tushare_namechange": _rules(
        RAW_NAMECHANGE_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_namechange": _rules(
        SILVER_NAMECHANGE_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_stock_identity_map": _rules(
        SILVER_STOCK_IDENTITY_MAP_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_dc_industry_hierarchy": _rules(
        SILVER_DC_INDUSTRY_HIERARCHY_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="DC_INDUSTRY_HIERARCHY_P1",
        retention_allowed=True,
    ),
    "raw_tushare_suspend_d": _rules(
        RAW_SUSPEND_D_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_stock_suspend_daily": _rules(
        SILVER_SUSPEND_D_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "raw_tushare_stock_daily": _rules(
        RAW_STOCK_DAILY_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "raw_tushare_stk_nineturn": _rules(
        RAW_STK_NINETURN_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="STK_NINETURN_N3",
        retention_allowed=True,
    ),
    "silver_stock_nineturn_daily": _rules(
        SILVER_STOCK_NINETURN_DAILY_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="STK_NINETURN_N3",
        retention_allowed=True,
    ),
    "silver_stock_daily": _rules(
        SILVER_STOCK_DAILY_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "raw_tushare_adj_factor": _rules(
        RAW_ADJ_FACTOR_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_adj_factor": _rules(
        SILVER_ADJ_FACTOR_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    # Board sensors use their dedicated batch lake-readiness helpers rather
    # than the shared AssetReadinessSpec registry.
    "raw_tushare_dc_index": _rules(
        (RAW_DC_BOARD_CHECKS[0],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M4",
        retention_allowed=True,
    ),
    "raw_tushare_dc_member": _rules(
        (RAW_DC_BOARD_CHECKS[1],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M4",
        retention_allowed=True,
    ),
    "raw_tushare_dc_daily": _rules(
        (RAW_DC_BOARD_CHECKS[2],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M4",
        retention_allowed=True,
    ),
    "silver_dc_index": _rules(
        (SILVER_DC_BOARD_CHECKS[0],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M6",
        retention_allowed=True,
    ),
    "silver_dc_member": _rules(
        (SILVER_DC_BOARD_CHECKS[1],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M6",
        retention_allowed=True,
    ),
    "silver_dc_daily": _rules(
        (SILVER_DC_BOARD_CHECKS[2],),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="M6",
        retention_allowed=True,
    ),
    "raw_index_global": _rules(
        INDEX_GLOBAL_RAW_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="INDEX_GLOBAL_P5",
        retention_allowed=True,
    ),
    "silver_index_global": _rules(
        INDEX_GLOBAL_SILVER_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="INDEX_GLOBAL_P5",
        retention_allowed=True,
    ),
    **_index_mins_asset_rules(),
    **_major_index_mins_asset_rules(),
    "raw_tushare_idx_factor_pro": _rules(
        IDX_FACTOR_PRO_RAW_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="IDX_FACTOR_PRO_M2",
        readiness=False,
        retention_allowed=True,
    ),
    **_planned_etf_asset_rules(),
    **_planned_index_technical_asset_rules(),
    "gold_major_index_daily_nineturn": _rules(
        GOLD_MAJOR_INDEX_DAILY_NINETURN_CHECKS,
        category=KEEP_BLOCKING_DAGSTER,
        phase="MAJOR_INDEX_NINETURN_M4B",
        readiness=True,
        retention_allowed=True,
    ),
    **{
        f"gold_major_index_mins_nineturn_{freq}m": _rules(
            check_names,
            category=RETENTION_ONLY,
            phase="MAJOR_INDEX_NINETURN_M4B",
            readiness=False,
            retention_allowed=True,
        )
        for freq, check_names in GOLD_MAJOR_INDEX_MINS_NINETURN_CHECKS_BY_FREQ.items()
    },
    "prod_core_index_daily_nineturn": _rules(
        PROD_CORE_INDEX_DAILY_NINETURN_CHECKS,
        category=RETENTION_ONLY,
        phase="MAJOR_INDEX_NINETURN_M4B",
        readiness=False,
        retention_allowed=True,
    ),
    "gold_stock_daily_qfq_nineturn": _rules(
        GOLD_STOCK_DAILY_QFQ_NINETURN_CHECKS,
        category=KEEP_BLOCKING_DAGSTER,
        phase="STK_NINETURN_N3",
        readiness=True,
        retention_allowed=True,
    ),
    "prod_core_stock_daily_qfq_nineturn": _rules(
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CHECKS,
        category=RETENTION_ONLY,
        phase="STK_NINETURN_SERVING",
        readiness=False,
        retention_allowed=True,
    ),
    **{
        f"gold_stk_mins_qfq_nineturn_{freq}m": _rules(
            check_names,
            category=RETENTION_ONLY,
            phase="STK_NINETURN_N3",
            readiness=False,
            retention_allowed=True,
        )
        for freq, check_names in GOLD_STK_MINS_QFQ_NINETURN_CHECKS_BY_FREQ.items()
    },
    "gold_stock_daily_qfq": _rules(
        GOLD_STOCK_DAILY_QFQ_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P8",
        readiness=True,
        retention_allowed=True,
    ),
    "gold_dc_daily_technical": _rules(
        GOLD_DC_DAILY_TECHNICAL_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P4",
        readiness=True,
        retention_allowed=True,
    ),
    **_stk_mins_asset_rules(),
    "raw_tushare_index_basic": _rules(
        RAW_INDEX_BASIC_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        retention_allowed=True,
    ),
    "silver_index_basic": _rules(
        SILVER_INDEX_BASIC_CHECKS,
        category=MERGE_BLOCKING_DAGSTER,
        phase="P5",
        readiness=True,
        retention_allowed=True,
    ),
    "raw_index_daily": _rules(
        RAW_INDEX_DAILY_CHECKS,
        category=KEEP_BLOCKING_DAGSTER,
        phase="P2",
        readiness=True,
        retention_allowed=True,
    ),
    "silver_index_daily": _rules(
        SILVER_INDEX_DAILY_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P2",
        readiness=True,
        retention_allowed=True,
    ),
    "gold_market_major_indices_daily": _rules(
        GOLD_MARKET_MAJOR_INDICES_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P2",
        readiness=True,
        retention_allowed=True,
    ),
    "gold_market_breadth_daily": _rules(
        GOLD_MARKET_BREADTH_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P4",
        retention_allowed=True,
    ),
    "gold_stock_return_distribution": _rules(
        GOLD_STOCK_RETURN_DISTRIBUTION_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P4",
        retention_allowed=True,
    ),
    "gold_wealth_market_turnover": _rules(
        ("gold_wealth_market_turnover_integrity_check",),
        category=KEEP_BLOCKING_DAGSTER,
        phase="P0.1",
        retention_allowed=True,
    ),
    "ch_share_fact_market_breadth_daily": _rules(
        CH_MARKET_BREADTH_CHECKS,
        category=MOVE_TO_OFFLINE_AUDIT,
        phase="P4",
        retention_allowed=True,
    ),
    "prod_ch_share_fact_market_breadth_daily": _rules(
        PROD_CH_MARKET_BREADTH_CHECKS,
        category=MOVE_TO_OFFLINE_AUDIT,
        phase="P4",
        retention_allowed=False,
    ),
    "ch_dc_daily_technical": _rules(
        ("ch_dc_daily_technical_core_check",),
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P2",
        readiness=True,
        retention_allowed=True,
    ),
    "prod_ch_dc_daily_technical": _rules(
        PROD_CH_DC_DAILY_TECHNICAL_CHECKS,
        category=MOVE_TO_SENSOR_LAKE_READINESS,
        phase="P3",
        readiness=True,
        retention_allowed=True,
    ),
    "lake_root_health": _rules(
        LAKE_ROOT_HEALTH_CHECKS,
        category=KEEP_BLOCKING_DAGSTER,
        phase="P5",
        retention_allowed=False,
    ),
}

PROTECTED_CHECK_GOVERNANCE = {
    check_name: _rule(
        category=KEEP_BLOCKING_DAGSTER,
        phase="P0.1",
        readiness=True,
        retention_allowed=False,
        protected_reason="repair/status/completion state ledger",
    )
    for check_name in STK_MINS_RETENTION_PROTECTED_CHECK_NAMES
}


def _catalog_blocking_checks_by_asset() -> dict[str, tuple[str, ...]]:
    return {
        entry.asset_key: tuple(entry.blocking_check_names)
        for entry in list_lake_asset_catalog_entries()
        if entry.blocking_check_names
    }


def _active_blocking_checks_by_asset() -> dict[str, set[str]]:
    check_names: dict[str, set[str]] = {}
    for module_info in pkgutil.iter_modules(checks_pkg.__path__):
        if module_info.name.startswith("__"):
            continue
        module = importlib.import_module(f"orchestrator.defs.checks.{module_info.name}")
        for value in vars(module).values():
            specs = getattr(value, "check_specs", None)
            if specs is None:
                continue
            for spec in specs:
                if not spec.blocking:
                    continue
                check_names.setdefault(spec.asset_key.to_user_string(), set()).add(
                    spec.name
                )
    return check_names


def _iter_readiness_specs(value: object) -> tuple[AssetReadinessSpec, ...]:
    if isinstance(value, AssetReadinessSpec):
        return (value,)
    if type(value) is tuple:
        return tuple(item for item in value if isinstance(item, AssetReadinessSpec))
    return ()


def _readiness_check_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    sensor_modules = tuple(
        importlib.import_module(f"orchestrator.defs.sensors.{module_info.name}")
        for module_info in pkgutil.iter_modules(sensors_pkg.__path__)
        if not module_info.name.startswith("__")
    )
    for module in sensor_modules:
        for value in vars(module).values():
            for spec in _iter_readiness_specs(value):
                for check_name in spec.blocking_check_names:
                    pairs.add((spec.asset_key.to_user_string(), check_name))
    return pairs


class AssetCheckIncrementalGovernanceTests(unittest.TestCase):
    def test_all_catalog_blocking_checks_have_incremental_governance_rule(
        self,
    ) -> None:
        catalog_checks = _catalog_blocking_checks_by_asset()

        self.assertEqual(set(ASSET_CHECK_GOVERNANCE), set(catalog_checks))
        for asset_key, check_names in catalog_checks.items():
            with self.subTest(asset=asset_key):
                rules = ASSET_CHECK_GOVERNANCE[asset_key]
                self.assertEqual(set(rules), set(check_names))
                for rule in rules.values():
                    self.assertIn(rule.category, GOVERNANCE_CATEGORIES)
                    self.assertTrue(rule.implementation_phase)
                    if rule.protected_reason:
                        self.assertFalse(rule.retention_allowed)

    def test_governance_matrix_matches_active_blocking_check_definitions(self) -> None:
        active_checks = {
            asset_key: check_names
            for asset_key, check_names in _active_blocking_checks_by_asset().items()
            if asset_key in ASSET_CHECK_GOVERNANCE
            and asset_key not in PLANNED_CATALOG_ASSET_KEYS
        }
        governed_checks = {
            asset_key: set(rules)
            for asset_key, rules in ASSET_CHECK_GOVERNANCE.items()
            if asset_key not in PLANNED_CATALOG_ASSET_KEYS
        }

        self.assertEqual(active_checks, governed_checks)

    def test_sensor_readiness_checks_are_declared_in_governance_matrix(self) -> None:
        governed_pairs = {
            (asset_key, check_name)
            for asset_key, rules in ASSET_CHECK_GOVERNANCE.items()
            for check_name, rule in rules.items()
            if rule.participates_in_sensor_readiness
        }
        actual_pairs = {
            pair
            for pair in _readiness_check_pairs()
            if pair[0] in ASSET_CHECK_GOVERNANCE
        }

        self.assertEqual(actual_pairs, governed_pairs)

    def test_protected_repair_status_checks_are_not_retention_candidates(self) -> None:
        catalog_check_names = {
            check_name
            for check_names in _catalog_blocking_checks_by_asset().values()
            for check_name in check_names
        }

        self.assertEqual(
            set(PROTECTED_CHECK_GOVERNANCE),
            set(STK_MINS_RETENTION_PROTECTED_CHECK_NAMES),
        )
        self.assertTrue(set(PROTECTED_CHECK_GOVERNANCE).isdisjoint(catalog_check_names))
        for check_name, rule in PROTECTED_CHECK_GOVERNANCE.items():
            with self.subTest(check=check_name):
                self.assertEqual(rule.category, KEEP_BLOCKING_DAGSTER)
                self.assertFalse(rule.retention_allowed)
                self.assertTrue(rule.protected_reason)

    def test_checks_only_jobs_never_select_materializable_assets(self) -> None:
        issues = []
        for path in sorted(JOBS_DIR.glob("*.py")):
            source = path.read_text()
            for match in re.finditer(
                r"(?P<name>[A-Za-z0-9_]*check_refresh_job)\s*="
                r"\s*dg\.define_asset_job\(",
                source,
            ):
                start = match.start()
                next_assignment = re.search(r"\n[A-Za-z0-9_]+\s*=", source[match.end() :])
                end = (
                    match.end() + next_assignment.start()
                    if next_assignment is not None
                    else len(source)
                )
                job_source = source[start:end]
                if "AssetSelection.assets" in job_source:
                    issues.append(
                        f"{path}:{match.group('name')} must not select assets"
                    )
                if "AssetSelection.checks_for_assets" not in job_source:
                    issues.append(
                        f"{path}:{match.group('name')} must select checks_for_assets"
                    )

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
