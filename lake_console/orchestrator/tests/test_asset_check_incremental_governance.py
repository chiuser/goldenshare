from __future__ import annotations

import importlib
import pkgutil
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

import orchestrator.defs.checks as checks_pkg
from orchestrator.defs.bootstrap.stk_mins_event_history_retention import (
    STK_MINS_RETENTION_PROTECTED_CHECK_NAMES,
)
from orchestrator.defs.catalog import list_lake_asset_catalog_entries
from orchestrator.defs.sensors import (
    gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor as macd_kdj_sensor_readiness,
)
from orchestrator.defs.sensors import readiness
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
    "raw_trade_calendar_contains_required_exchange",
    "raw_trade_calendar_file_exists",
    "raw_trade_calendar_required_columns",
)
SILVER_TRADE_CALENDAR_CHECKS = (
    "silver_trade_calendar_required_columns_non_null",
    "silver_trade_calendar_unique_exchange_trade_date",
)
RAW_STOCK_BASIC_CHECKS = (
    "raw_stock_basic_file_exists",
    "raw_stock_basic_required_columns",
    "raw_stock_basic_row_count_positive",
    "raw_stock_basic_ts_code_present",
)
SILVER_STOCK_BASIC_CHECKS = (
    "silver_stock_basic_cny_stock_universe_check",
    "silver_stock_basic_current_listed_only",
    "silver_stock_basic_has_listed_records",
    "silver_stock_basic_lifecycle_dates_valid",
    "silver_stock_basic_required_columns_non_null",
    "silver_stock_basic_unique_ts_code",
)
SILVER_STOCK_LIFECYCLE_CHECKS = (
    "silver_stock_lifecycle_cny_stock_universe_check",
    "silver_stock_lifecycle_dates_valid_check",
    "silver_stock_lifecycle_file_exists_check",
    "silver_stock_lifecycle_required_columns_and_types_check",
    "silver_stock_lifecycle_required_fields_non_null_check",
    "silver_stock_lifecycle_unique_ts_code_check",
)
RAW_NAMECHANGE_CHECKS = (
    "raw_namechange_date_string_format_valid",
    "raw_namechange_exact_duplicate_absent",
    "raw_namechange_file_exists",
    "raw_namechange_required_columns",
    "raw_namechange_required_fields_non_null",
    "raw_namechange_row_count_positive",
    "raw_namechange_schema_matches_tushare_contract",
)
SILVER_NAMECHANGE_CHECKS = (
    "silver_namechange_current_open_interval_unique",
    "silver_namechange_date_order_valid",
    "silver_namechange_exact_duplicate_absent",
    "silver_namechange_file_exists",
    "silver_namechange_interval_overlap_absent",
    "silver_namechange_required_columns",
    "silver_namechange_required_fields_non_null",
    "silver_namechange_row_count_positive",
    "silver_namechange_schema_matches_contract",
    "silver_namechange_unknown_adjacent_gap_absent",
)
SILVER_STOCK_IDENTITY_MAP_CHECKS = (
    "silver_stock_identity_map_conflicting_mapping_absent",
    "silver_stock_identity_map_date_ranges_valid",
    "silver_stock_identity_map_file_exists",
    "silver_stock_identity_map_known_confidence",
    "silver_stock_identity_map_known_identity_source",
    "silver_stock_identity_map_latest_code_exists_in_stock_basic",
    "silver_stock_identity_map_latest_ts_code_present",
    "silver_stock_identity_map_row_count_positive",
    "silver_stock_identity_map_schema_matches_contract",
    "silver_stock_identity_map_seed_latest_code_explainable",
    "silver_stock_identity_map_source_ts_code_present",
    "silver_stock_identity_map_source_ts_code_unique",
)
RAW_SUSPEND_D_CHECKS = (
    "raw_suspend_d_file_exists",
    "raw_suspend_d_partition_date_matches",
    "raw_suspend_d_required_columns",
    "raw_suspend_d_schema_matches_tushare_contract",
    "raw_suspend_d_stock_partition_key_allowed",
)
SILVER_SUSPEND_D_CHECKS = (
    "silver_suspend_d_known_type_values",
    "silver_suspend_d_stock_partition_key_allowed",
    "silver_suspend_d_unique_business_key",
)
RAW_STOCK_DAILY_CHECKS = (
    "raw_stock_daily_covers_expected_tradable_universe",
    "raw_stock_daily_file_exists",
    "raw_stock_daily_partition_date_matches",
    "raw_stock_daily_required_columns",
    "raw_stock_daily_row_count_matches_expected_tradable_count",
    "raw_stock_daily_row_count_positive",
    "raw_stock_daily_stock_partition_key_allowed",
    "raw_stock_daily_unique_ts_code_trade_date",
)
SILVER_STOCK_DAILY_CHECKS = (
    "silver_stock_daily_after_list_date_only",
    "silver_stock_daily_bj_after_market_open_only",
    "silver_stock_daily_conflicting_duplicate_absent",
    "silver_stock_daily_covers_expected_tradable_universe",
    "silver_stock_daily_partition_date_matches",
    "silver_stock_daily_price_sanity",
    "silver_stock_daily_required_columns_non_null",
    "silver_stock_daily_row_count_positive",
    "silver_stock_daily_stock_lifecycle_covered",
    "silver_stock_daily_stock_partition_key_allowed",
    "silver_stock_daily_unique_ts_code_trade_date",
)
RAW_ADJ_FACTOR_CHECKS = (
    "raw_adj_factor_file_exists",
    "raw_adj_factor_partition_date_matches",
    "raw_adj_factor_positive_factor",
    "raw_adj_factor_required_columns",
    "raw_adj_factor_row_count_positive",
    "raw_adj_factor_schema_matches_tushare_contract",
    "raw_adj_factor_stock_current_partition_key_allowed",
    "raw_adj_factor_unique_ts_code_trade_date",
)
SILVER_ADJ_FACTOR_CHECKS = (
    "silver_adj_factor_coverage_complete",
    "silver_adj_factor_file_exists",
    "silver_adj_factor_listed_stock_only",
    "silver_adj_factor_partition_date_matches",
    "silver_adj_factor_positive_factor",
    "silver_adj_factor_required_columns",
    "silver_adj_factor_row_count_positive",
    "silver_adj_factor_schema_matches_contract",
    "silver_adj_factor_stock_current_partition_key_allowed",
    "silver_adj_factor_unique_ts_code_trade_date",
)
RAW_STK_MINS_CHECKS = (
    "raw_stk_mins_file_exists_and_row_count_positive",
    "raw_stk_mins_freq_matches_asset",
    "raw_stk_mins_partition_date_matches",
    "raw_stk_mins_price_volume_sanity",
    "raw_stk_mins_schema_matches_contract",
    "raw_stk_mins_stock_mins_partition_key_registered",
    "raw_stk_mins_unique_ts_code_trade_time",
)
SILVER_STK_MINS_CHECKS = (
    "silver_stk_mins_codes_exist_in_stock_daily",
    "silver_stk_mins_exchange_matches_suffix",
    "silver_stk_mins_file_exists_and_row_count_positive",
    "silver_stk_mins_freq_and_partition_match",
    "silver_stk_mins_name_timeline_covered",
    "silver_stk_mins_no_full_day_suspend_structural_rows",
    "silver_stk_mins_price_sanity",
    "silver_stk_mins_schema_matches_contract",
    "silver_stk_mins_unique_ts_code_trade_time",
    "silver_stk_mins_volume_amount_sanity",
)
GOLD_STK_MINS_QFQ_NATIVE_CHECKS = (
    "gold_stk_mins_qfq_factor_coverage_complete",
    "gold_stk_mins_qfq_file_exists_and_row_count_positive",
    "gold_stk_mins_qfq_freq_date_path_match",
    "gold_stk_mins_qfq_price_sanity",
    "gold_stk_mins_qfq_schema_matches_contract",
    "gold_stk_mins_qfq_unique_ts_code_trade_time",
    "gold_stk_mins_qfq_formula_matches_silver_adj_factor",
    "gold_stk_mins_qfq_row_count_matches_silver",
)
GOLD_STK_MINS_QFQ_DERIVED_CHECKS = (
    "gold_stk_mins_qfq_derived_formula_matches_source",
    "gold_stk_mins_qfq_derived_row_count_matches_source_windows",
    "gold_stk_mins_qfq_derived_source_ready",
    "gold_stk_mins_qfq_file_exists_and_row_count_positive",
    "gold_stk_mins_qfq_freq_date_path_match",
    "gold_stk_mins_qfq_price_sanity",
    "gold_stk_mins_qfq_schema_matches_contract",
    "gold_stk_mins_qfq_unique_ts_code_trade_time",
)
MACD_KDJ_INDICATOR_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_file_exists_and_schema_check",
    "gold_stk_mins_qfq_macd_kdj_source_ready_check",
    "gold_stk_mins_qfq_macd_kdj_row_count_matches_qfq_check",
    "gold_stk_mins_qfq_macd_kdj_formula_sample_check",
)
MACD_KDJ_STATE_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check",
    "gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check",
)
RAW_INDEX_BASIC_CHECKS = (
    "raw_index_basic_date_strings_parseable",
    "raw_index_basic_file_exists",
    "raw_index_basic_required_columns",
    "raw_index_basic_row_count_positive",
    "raw_index_basic_unique_ts_code",
)
SILVER_INDEX_BASIC_CHECKS = (
    "silver_index_basic_file_exists",
    "silver_index_basic_no_terminated_indexes",
    "silver_index_basic_required_columns_and_types",
    "silver_index_basic_required_fields_non_null",
    "silver_index_basic_row_count_positive",
    "silver_index_basic_unique_ts_code",
)
RAW_INDEX_DAILY_CHECKS = (
    "raw_index_daily_code_coverage_check",
    "raw_index_daily_file_contract_check",
)
SILVER_INDEX_DAILY_CHECKS = (
    "silver_index_daily_conflicting_duplicate_absent",
    "silver_index_daily_partition_date_matches",
    "silver_index_daily_price_sanity",
    "silver_index_daily_registered_code_coverage",
    "silver_index_daily_required_columns_and_types",
    "silver_index_daily_row_count_positive",
    "silver_index_daily_unique_ts_code_trade_date",
)
GOLD_MARKET_MAJOR_INDICES_CHECKS = (
    "gold_market_major_indices_daily_file_exists",
    "gold_market_major_indices_daily_partition_date_matches",
    "gold_market_major_indices_daily_price_sanity",
    "gold_market_major_indices_daily_rank_matches_active_seed_order",
    "gold_market_major_indices_daily_required_columns_and_types",
    "gold_market_major_indices_daily_row_count_matches_seed",
    "gold_market_major_indices_daily_seed_codes_present",
    "gold_market_major_indices_daily_unique_ts_code",
    "gold_market_major_indices_seed_codes_exist_in_index_basic",
    "gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes",
)
GOLD_MARKET_BREADTH_CHECKS = (
    "gold_market_breadth_counts_add_up",
    "gold_market_breadth_matches_silver_recompute",
    "gold_market_breadth_red_rate_formula",
    "gold_market_breadth_red_rate_range",
    "gold_market_breadth_row_count_is_one",
    "gold_market_breadth_stock_partition_key_allowed",
    "gold_market_breadth_total_count_matches_silver",
    "gold_market_breadth_total_count_positive",
)
GOLD_STOCK_RETURN_DISTRIBUTION_CHECKS = (
    "gold_stock_return_distribution_counts_add_up",
    "gold_stock_return_distribution_partition_date_matches",
    "gold_stock_return_distribution_recomputed_from_silver",
    "gold_stock_return_distribution_row_count_is_one",
    "gold_stock_return_distribution_stock_partition_key_allowed",
    "gold_stock_return_distribution_total_count_matches_silver",
)
CH_MARKET_BREADTH_CHECKS = (
    "ch_share_fact_market_breadth_breadth_fields_match_gold",
    "ch_share_fact_market_breadth_date_matches_partition",
    "ch_share_fact_market_breadth_distribution_fields_match_gold",
    "ch_share_fact_market_breadth_flat_count_matches_gold",
    "ch_share_fact_market_breadth_row_count_is_one",
    "ch_share_fact_market_breadth_total_count_matches_gold",
)
PROD_CH_MARKET_BREADTH_CHECKS = (
    "prod_ch_share_fact_market_breadth_date_matches_partition",
    "prod_ch_share_fact_market_breadth_row_count_is_one",
    "prod_ch_share_fact_market_breadth_row_matches_local",
    "prod_ch_share_fact_market_breadth_updated_at_not_older_than_local",
)
LAKE_ROOT_HEALTH_CHECKS = (
    "duckdb_temp_directory_ready",
    "lake_root_disk_space_ready",
    "lake_root_read_write_ready",
    "lake_root_required_paths_ready",
)


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
    for module in (readiness, macd_kdj_sensor_readiness):
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
                for check_name, rule in rules.items():
                    self.assertIn(rule.category, GOVERNANCE_CATEGORIES)
                    self.assertTrue(rule.implementation_phase)
                    if rule.protected_reason:
                        self.assertFalse(rule.retention_allowed)

    def test_governance_matrix_matches_active_blocking_check_definitions(self) -> None:
        active_checks = {
            asset_key: check_names
            for asset_key, check_names in _active_blocking_checks_by_asset().items()
            if asset_key in ASSET_CHECK_GOVERNANCE
        }
        governed_checks = {
            asset_key: set(rules)
            for asset_key, rules in ASSET_CHECK_GOVERNANCE.items()
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
