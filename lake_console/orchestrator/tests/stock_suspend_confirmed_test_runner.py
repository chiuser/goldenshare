"""Task-local, stdlib-only launcher for I03-I08 isolation tests in fixed batches.

No Dagster imports, environment discovery, dependency installation or cleanup.
Adapter execution is separately selected after the approved I01-I08 review.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import select
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SUPPORT = PROJECT / "tests/stock_suspend_confirmed_test_support.py"
TEST = PROJECT / "tests/test_stock_suspend_confirmed_isolation.py"
SOURCE = PROJECT / "src/orchestrator"
ISOLATION_BATCHES = (
    ("I03-I04", 16, (
        "test_i03_actual_resource_root", "test_i03_factory_rejects_before_path_io",
        "test_i03_detects_real_resource_default_without_io", "test_i04_input_path_preflight",
    )),
    ("I05", 14, (
        "test_i05_real_duckdb_resource", "test_i05_rejects_wrong_effective_setting",
        "test_i05_rejects_bad_connection_arguments", "test_i05_rejects_formal_connection_entry",
    )),
    ("I06", 16, (
        "test_i06_real_instance_persistence", "test_i06_rejects_local_instance_arguments",
        "test_i06_rejects_instance_discovery", "test_i06_python_network_guard",
        "test_i06_native_network_denial",
    )),
)
STARTUP_PROBES = (
    "guard_missing", "guard_late", "policy_missing", "policy_invalid", "policy_mismatch",
    "selfcheck_failed_stale", "collection_allowed", "collection_denied", "skip", "xfail",
)
# Actual import closure of resources.py, not permission for all defs or CSV data.
RESOURCE_SOURCE_FILES = (
    "__init__.py", "defs/__init__.py", "defs/resources.py",
    "defs/duckdb_connection.py", "defs/paths.py", "defs/tushare_request_policy.py",
    "defs/health/__init__.py", "defs/health/lake_root.py",
    "defs/notifications/__init__.py", "defs/notifications/feishu.py",
    "defs/run_contracts/__init__.py", "defs/run_contracts/etf_basic.py",
    "defs/run_contracts/etf_daily.py", "defs/run_contracts/etf_mins.py",
    "defs/run_contracts/idx_factor_pro.py", "defs/run_contracts/index_mins.py",
    "defs/run_contracts/major_index_mins.py",
    "defs/run_contracts/major_index_mins_technical.py",
    "defs/run_contracts/major_index_nineturn.py", "defs/run_contracts/qfq_nineturn.py",
    "defs/run_contracts/stk_mins.py", "defs/run_contracts/configs.py",
    "defs/run_contracts/cn_a_derived_minute_bars.py",
    "seeds/__init__.py", "seeds/market/__init__.py", "seeds/market/major_indices.py",
)
ADAPTER_SOURCE_FILES = (
    "defs/stock_suspend_confirmed_contract.py", "defs/assets/__init__.py",
    "defs/assets/stock_suspend_confirmed.py", "defs/checks/__init__.py",
    "defs/checks/stock_suspend_confirmed_checks.py", "defs/run_contracts/asset_column_schemas.py",
    "defs/run_contracts/column_schema.py", "defs/run_contracts/asset_tags.py",
    "defs/run_contracts/metadata.py", "defs/catalog/__init__.py", "defs/catalog/name_mapping.py",
)
ADAPTER_BATCHES = (
    ("C-encoding", "contracts", 11, ("test_literal_encoding_and_real_approval_rejection",
        "test_sample_approval_and_same_count_changed_key", "test_content_negative_cases")),
    ("C-schema-path", "contracts", 12, ("test_physical_schema_rejected_before_cast",
        "test_reordered_compressed_file_has_same_logical_identity", "test_invalid_operation_paths", "test_path_rejections")),
    ("C08-C09", "contracts", 11, ("test_c08_inspection_separates_schema_and_count", "test_c09_inspection_io_and_identity")),
    ("D-path-publication", "dagster", 11, ("test_external_spec", "test_path_and_publication_failures")),
    ("D-validation", "dagster", 9, ("test_validation_and_storage",)),
    ("D-input-errors", "dagster", 5, ("test_input_error_classification",)),
)
MERGE_SOURCE_FILES = (
    "defs/duckdb_sql.py", "defs/corrections/__init__.py",
    "defs/corrections/suspend_timing.py",
    "defs/stock_suspend_confirmed_contract.py", "defs/run_contracts/asset_column_schemas.py",
    "defs/run_contracts/column_schema.py",
)
WRITER_SOURCE_FILES = (
    "defs/assets/suspend_d.py", "defs/partitions.py", "defs/tushare_api_io.py",
    "utils/__init__.py", "utils/dg_log_helper.py",
)
INTEGRATION_SOURCE_FILES = (
    "defs/jobs/__init__.py", "defs/jobs/suspend_update.py",
    "defs/checks/suspend_d_checks.py", "defs/checks/stock_partition_checks.py",
    "defs/sensors/__init__.py", "defs/sensors/suspend_d_sensor.py",
    "defs/sensors/cn_a_trade_day_sensor.py", "defs/sensors/stock_trade_day_sensor.py",
    "defs/sensors/readiness.py", "defs/asset_guards/__init__.py",
    "defs/asset_guards/bounded_continuity.py", "defs/asset_guards/stock_daily.py",
    "defs/assets/market_breadth.py", "defs/assets/stock_basic.py",
    "defs/assets/stock_daily.py", "defs/assets/stock_lifecycle.py",
    "defs/assets/stock_return_distribution.py", "defs/catalog/lake_assets.py",
    "defs/run_contracts/cursor_payloads.py", "defs/run_contracts/cursors.py",
    "defs/run_contracts/dc_board.py", "defs/run_contracts/dc_daily_technical.py",
    "defs/run_contracts/dc_daily_technical_serving.py", "defs/run_contracts/index_global.py",
    "defs/run_contracts/requests.py", "defs/run_contracts/run_keys.py",
    "defs/run_contracts/sensor_tags.py",
)
# Frozen exact source inventory for full consumer/governance discovery.
CONSUMER_SOURCE_FILES = (
    "__init__.py",
    "analysis/__init__.py",
    "analysis/index_wave/__init__.py",
    "analysis/index_wave/bars.py",
    "analysis/index_wave/calibration.py",
    "analysis/index_wave/grammar.py",
    "analysis/index_wave/identities.py",
    "analysis/index_wave/pivot.py",
    "analysis/index_wave/profiles.py",
    "analysis/index_wave/progression.py",
    "analysis/index_wave/replay.py",
    "analysis/index_wave/scenarios.py",
    "analysis/index_wave/scoring.py",
    "analysis/index_wave/swings.py",
    "analysis/index_wave_research/__init__.py",
    "analysis/index_wave_research/research_calibration.py",
    "analysis/index_wave_research/research_sources.py",
    "analysis/index_wave_research/research_validation.py",
    "analysis/index_wave_research/source_adapters.py",
    "audits/__init__.py",
    "audits/stk_mins_qfq_performance.py",
    "audits/stk_mins_silver_strict_audit.py",
    "definitions.py",
    "defs/__init__.py",
    "defs/asset_guards/__init__.py",
    "defs/asset_guards/adj_factor_lake_readiness.py",
    "defs/asset_guards/bounded_continuity.py",
    "defs/asset_guards/cn_a_gold_minute_lake_readiness.py",
    "defs/asset_guards/dc_board_lake_readiness.py",
    "defs/asset_guards/dc_board_raw_quality.py",
    "defs/asset_guards/dc_board_relations.py",
    "defs/asset_guards/dc_board_silver_lake_readiness.py",
    "defs/asset_guards/dc_board_silver_quality.py",
    "defs/asset_guards/dc_board_source_probe.py",
    "defs/asset_guards/dc_daily_silver_repair.py",
    "defs/asset_guards/dc_daily_silver_repair_producer.py",
    "defs/asset_guards/dc_daily_technical_clickhouse_readiness.py",
    "defs/asset_guards/dc_daily_technical_lake_readiness.py",
    "defs/asset_guards/dc_daily_technical_quality.py",
    "defs/asset_guards/etf_basic_readiness.py",
    "defs/asset_guards/etf_daily_lake_readiness.py",
    "defs/asset_guards/etf_daily_source_probe.py",
    "defs/asset_guards/etf_mins_lake_readiness.py",
    "defs/asset_guards/etf_mins_prod_readiness.py",
    "defs/asset_guards/idx_factor_pro_lake_readiness.py",
    "defs/asset_guards/idx_factor_pro_source_probe.py",
    "defs/asset_guards/index_global_lake_readiness.py",
    "defs/asset_guards/index_mins_gold.py",
    "defs/asset_guards/index_mins_lake_readiness.py",
    "defs/asset_guards/major_index_mins_gold.py",
    "defs/asset_guards/major_index_mins_lake_readiness.py",
    "defs/asset_guards/major_index_mins_source_probe.py",
    "defs/asset_guards/major_index_mins_technical.py",
    "defs/asset_guards/major_index_nineturn.py",
    "defs/asset_guards/market_breadth_lake_readiness.py",
    "defs/asset_guards/market_major_indices_lake_readiness.py",
    "defs/asset_guards/qfq_nineturn_lake_readiness.py",
    "defs/asset_guards/stk_mins_continuity.py",
    "defs/asset_guards/stk_mins_lake_readiness.py",
    "defs/asset_guards/stk_mins_prod_readiness.py",
    "defs/asset_guards/stk_mins_qfq_factor_repair.py",
    "defs/asset_guards/stk_mins_qfq_macd_kdj.py",
    "defs/asset_guards/stk_mins_stock_universe.py",
    "defs/asset_guards/stk_nineturn_lake_readiness.py",
    "defs/asset_guards/stock_daily.py",
    "defs/asset_guards/stock_daily_qfq_factor_repair.py",
    "defs/asset_guards/stock_daily_trend_channel_lake_readiness.py",
    "defs/asset_guards/stock_daily_trend_channel_repair.py",
    "defs/asset_guards/wealth_market_turnover_lake_readiness.py",
    "defs/assets/__init__.py",
    "defs/assets/adj_factor.py",
    "defs/assets/calendar.py",
    "defs/assets/clickhouse_serving.py",
    "defs/assets/dc_board.py",
    "defs/assets/dc_board_raw.py",
    "defs/assets/dc_board_silver.py",
    "defs/assets/dc_daily_technical.py",
    "defs/assets/dc_daily_technical_asset.py",
    "defs/assets/dc_daily_technical_repair.py",
    "defs/assets/dc_daily_technical_serving.py",
    "defs/assets/dc_industry_hierarchy.py",
    "defs/assets/etf_basic.py",
    "defs/assets/etf_daily.py",
    "defs/assets/etf_mins.py",
    "defs/assets/idx_factor_pro_raw.py",
    "defs/assets/idx_factor_pro_silver.py",
    "defs/assets/index_basic.py",
    "defs/assets/index_daily.py",
    "defs/assets/index_daily_nineturn_prod_core.py",
    "defs/assets/index_global_raw.py",
    "defs/assets/index_global_silver.py",
    "defs/assets/index_mins.py",
    "defs/assets/index_mins_gold.py",
    "defs/assets/index_mins_raw.py",
    "defs/assets/index_mins_silver.py",
    "defs/assets/index_mins_silver_defs.py",
    "defs/assets/index_mins_silver_repair.py",
    "defs/assets/lake_root_health.py",
    "defs/assets/major_index_mins_gold.py",
    "defs/assets/major_index_mins_raw.py",
    "defs/assets/major_index_mins_silver.py",
    "defs/assets/major_index_mins_technical.py",
    "defs/assets/major_index_nineturn.py",
    "defs/assets/market_breadth.py",
    "defs/assets/market_major_indices.py",
    "defs/assets/namechange.py",
    "defs/assets/qfq_nineturn.py",
    "defs/assets/stk_mins.py",
    "defs/assets/stk_mins_qfq_macd_kdj.py",
    "defs/assets/stk_nineturn.py",
    "defs/assets/stock_basic.py",
    "defs/assets/stock_daily.py",
    "defs/assets/stock_daily_qfq.py",
    "defs/assets/stock_daily_qfq_nineturn_prod_core.py",
    "defs/assets/stock_daily_trend_channel.py",
    "defs/assets/stock_identity_map.py",
    "defs/assets/stock_lifecycle.py",
    "defs/assets/stock_return_distribution.py",
    "defs/assets/stock_suspend_confirmed.py",
    "defs/assets/suspend_d.py",
    "defs/assets/wealth_market_turnover.py",
    "defs/assets/wealth_market_turnover_prod_core.py",
    "defs/assets/wealth_sector_hierarchy_prod_core.py",
    "defs/backfills/__init__.py",
    "defs/bootstrap/__init__.py",
    "defs/bootstrap/adj_factor_silver_history.py",
    "defs/bootstrap/asset_check_event_retention.py",
    "defs/bootstrap/asset_check_event_retention_cli.py",
    "defs/bootstrap/asset_check_event_retention_sample_delete.py",
    "defs/bootstrap/asset_check_event_retention_sample_delete_cli.py",
    "defs/bootstrap/cn_a_minute_gold_history.py",
    "defs/bootstrap/cn_a_minute_gold_history_cli.py",
    "defs/bootstrap/cn_a_minute_gold_p9_events.py",
    "defs/bootstrap/cn_a_minute_gold_p9_events_cli.py",
    "defs/bootstrap/dc_board_bootstrap.py",
    "defs/bootstrap/dc_board_bootstrap_apply.py",
    "defs/bootstrap/dc_board_bootstrap_apply_cli.py",
    "defs/bootstrap/dc_board_bootstrap_cli.py",
    "defs/bootstrap/dc_board_bootstrap_plan.py",
    "defs/bootstrap/dc_board_events.py",
    "defs/bootstrap/dc_board_events_cli.py",
    "defs/bootstrap/dc_daily_technical_clickhouse_bootstrap.py",
    "defs/bootstrap/dc_daily_technical_clickhouse_bootstrap_apply.py",
    "defs/bootstrap/dc_daily_technical_clickhouse_bootstrap_cli.py",
    "defs/bootstrap/dc_daily_technical_events.py",
    "defs/bootstrap/dc_daily_technical_events_cli.py",
    "defs/bootstrap/etf_daily_bootstrap_apply.py",
    "defs/bootstrap/etf_daily_bootstrap_audit.py",
    "defs/bootstrap/etf_daily_bootstrap_cli.py",
    "defs/bootstrap/etf_daily_bootstrap_events.py",
    "defs/bootstrap/etf_daily_bootstrap_plan.py",
    "defs/bootstrap/etf_daily_physical_batch_audit.py",
    "defs/bootstrap/etf_daily_raw_batch_audit.py",
    "defs/bootstrap/etf_mins_bootstrap.py",
    "defs/bootstrap/etf_mins_bootstrap_cli.py",
    "defs/bootstrap/etf_mins_raw_decision.py",
    "defs/bootstrap/etf_mins_raw_observation.py",
    "defs/bootstrap/event_history_retention_dry_run.py",
    "defs/bootstrap/event_history_retention_dry_run_cli.py",
    "defs/bootstrap/gold_stock_daily_qfq_history.py",
    "defs/bootstrap/gold_stock_daily_qfq_history_cli.py",
    "defs/bootstrap/gold_stock_daily_qfq_history_events.py",
    "defs/bootstrap/gold_stock_daily_qfq_history_events_cli.py",
    "defs/bootstrap/gold_stock_daily_qfq_history_reset.py",
    "defs/bootstrap/gold_stock_daily_qfq_history_reset_cli.py",
    "defs/bootstrap/historical_materialization_reconciliation.py",
    "defs/bootstrap/historical_materialization_reconciliation_cli.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_cli.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_events.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_events_cli.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_plan.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_promote.py",
    "defs/bootstrap/idx_factor_pro_bootstrap_stage.py",
    "defs/bootstrap/index_daily_000680_history_supplement_apply.py",
    "defs/bootstrap/index_daily_000680_history_supplement_apply_cli.py",
    "defs/bootstrap/index_daily_000680_history_supplement_audit.py",
    "defs/bootstrap/index_daily_000680_history_supplement_audit_cli.py",
    "defs/bootstrap/index_daily_000680_history_supplement_events.py",
    "defs/bootstrap/index_daily_000680_history_supplement_events_cli.py",
    "defs/bootstrap/index_daily_000680_history_supplement_plan.py",
    "defs/bootstrap/index_daily_000680_history_supplement_plan_cli.py",
    "defs/bootstrap/index_global_bootstrap_apply.py",
    "defs/bootstrap/index_global_bootstrap_apply_cli.py",
    "defs/bootstrap/index_global_bootstrap_cli.py",
    "defs/bootstrap/index_global_bootstrap_events.py",
    "defs/bootstrap/index_global_bootstrap_events_cli.py",
    "defs/bootstrap/index_global_bootstrap_plan.py",
    "defs/bootstrap/index_global_bootstrap_source_probe.py",
    "defs/bootstrap/index_global_bootstrap_source_probe_cli.py",
    "defs/bootstrap/index_mins_bootstrap_apply.py",
    "defs/bootstrap/index_mins_bootstrap_apply_cli.py",
    "defs/bootstrap/index_mins_bootstrap_cli.py",
    "defs/bootstrap/index_mins_bootstrap_events.py",
    "defs/bootstrap/index_mins_bootstrap_events_cli.py",
    "defs/bootstrap/index_mins_bootstrap_plan.py",
    "defs/bootstrap/major_index_daily_nineturn_serving_history.py",
    "defs/bootstrap/major_index_daily_nineturn_serving_history_cli.py",
    "defs/bootstrap/major_index_mins_bootstrap_apply.py",
    "defs/bootstrap/major_index_mins_bootstrap_apply_cli.py",
    "defs/bootstrap/major_index_mins_bootstrap_cli.py",
    "defs/bootstrap/major_index_mins_bootstrap_events.py",
    "defs/bootstrap/major_index_mins_bootstrap_events_cli.py",
    "defs/bootstrap/major_index_mins_bootstrap_plan.py",
    "defs/bootstrap/major_index_mins_bootstrap_stage.py",
    "defs/bootstrap/major_index_mins_bootstrap_stage_cli.py",
    "defs/bootstrap/major_index_mins_silver_fallback.py",
    "defs/bootstrap/major_index_mins_technical_bootstrap_cli.py",
    "defs/bootstrap/major_index_mins_technical_bootstrap_events.py",
    "defs/bootstrap/major_index_mins_technical_bootstrap_events_cli.py",
    "defs/bootstrap/major_index_mins_technical_history.py",
    "defs/bootstrap/major_index_nineturn_events.py",
    "defs/bootstrap/major_index_nineturn_events_cli.py",
    "defs/bootstrap/major_index_nineturn_history.py",
    "defs/bootstrap/major_index_nineturn_history_audit.py",
    "defs/bootstrap/major_index_nineturn_history_audit_cli.py",
    "defs/bootstrap/major_index_nineturn_history_cli.py",
    "defs/bootstrap/qfq_nineturn_events.py",
    "defs/bootstrap/qfq_nineturn_events_cli.py",
    "defs/bootstrap/qfq_nineturn_history.py",
    "defs/bootstrap/qfq_nineturn_history_cli.py",
    "defs/bootstrap/stk_mins_bse_history_recovery.py",
    "defs/bootstrap/stk_mins_bse_history_recovery_cli.py",
    "defs/bootstrap/stk_mins_bse_qfq_recovery.py",
    "defs/bootstrap/stk_mins_bse_recursive_events.py",
    "defs/bootstrap/stk_mins_bse_recursive_events_cli.py",
    "defs/bootstrap/stk_mins_bse_recursive_recovery.py",
    "defs/bootstrap/stk_mins_event_history_retention.py",
    "defs/bootstrap/stk_mins_event_history_retention_cli.py",
    "defs/bootstrap/stk_mins_event_history_retention_sample_delete.py",
    "defs/bootstrap/stk_mins_event_history_retention_sample_delete_cli.py",
    "defs/bootstrap/stk_mins_history_check_events.py",
    "defs/bootstrap/stk_mins_history_cli_contract.py",
    "defs/bootstrap/stk_mins_name_timeline_check_events.py",
    "defs/bootstrap/stk_mins_name_timeline_check_events_cli.py",
    "defs/bootstrap/stk_mins_qfq_bootstrap_events.py",
    "defs/bootstrap/stk_mins_qfq_canonical_history.py",
    "defs/bootstrap/stk_mins_qfq_canonical_history_cli.py",
    "defs/bootstrap/stk_mins_qfq_derived_bootstrap_events.py",
    "defs/bootstrap/stk_mins_qfq_derived_history.py",
    "defs/bootstrap/stk_mins_qfq_derived_history_cli.py",
    "defs/bootstrap/stk_mins_qfq_history.py",
    "defs/bootstrap/stk_mins_qfq_history_cli.py",
    "defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py",
    "defs/bootstrap/stk_mins_qfq_macd_kdj_history.py",
    "defs/bootstrap/stk_mins_qfq_macd_kdj_history_cli.py",
    "defs/bootstrap/stk_mins_qfq_macd_kdj_repair_completion_events.py",
    "defs/bootstrap/stk_mins_qfq_macd_kdj_repair_completion_events_cli.py",
    "defs/bootstrap/stk_mins_raw_replace_from_prod.py",
    "defs/bootstrap/stk_mins_raw_replace_from_prod_cli.py",
    "defs/bootstrap/stk_mins_silver_bootstrap_events.py",
    "defs/bootstrap/stk_mins_silver_history.py",
    "defs/bootstrap/stk_mins_silver_history_cli.py",
    "defs/bootstrap/stk_mins_silver_replace_from_raw.py",
    "defs/bootstrap/stk_mins_silver_replace_from_raw_cli.py",
    "defs/bootstrap/stk_mins_stock_year_materialization_reconciliation.py",
    "defs/bootstrap/stk_mins_stock_year_materialization_reconciliation_cli.py",
    "defs/bootstrap/stk_nineturn_events.py",
    "defs/bootstrap/stk_nineturn_events_cli.py",
    "defs/bootstrap/stk_nineturn_history.py",
    "defs/bootstrap/stk_nineturn_history_cli.py",
    "defs/bootstrap/stk_nineturn_partition_migration.py",
    "defs/bootstrap/stk_nineturn_partition_migration_cli.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_events.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_events_cli.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_history.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_history_cli.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_serving_events.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_no_price_serving_events_cli.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_serving_history.py",
    "defs/bootstrap/stock_daily_qfq_nineturn_serving_history_cli.py",
    "defs/bootstrap/stock_daily_trend_channel_event_reconciliation.py",
    "defs/bootstrap/stock_daily_trend_channel_event_reconciliation_cli.py",
    "defs/bootstrap/stock_daily_trend_channel_history.py",
    "defs/bootstrap/stock_daily_trend_channel_history_cli.py",
    "defs/bootstrap/stock_daily_trend_channel_runless_events.py",
    "defs/bootstrap/stock_daily_trend_channel_runless_events_cli.py",
    "defs/bootstrap/stock_suspend_confirmed.py",
    "defs/bootstrap/stock_suspend_confirmed_cli.py",
    "defs/bootstrap/stock_suspend_confirmed_events.py",
    "defs/bootstrap/wealth_market_turnover_history.py",
    "defs/bootstrap/wealth_market_turnover_history_cli.py",
    "defs/bootstrap/wealth_market_turnover_runless_events.py",
    "defs/bootstrap/wealth_market_turnover_runless_events_cli.py",
    "defs/catalog/__init__.py",
    "defs/catalog/lake_assets.py",
    "defs/catalog/name_mapping.py",
    "defs/checks/__init__.py",
    "defs/checks/adj_factor_checks.py",
    "defs/checks/calendar_checks.py",
    "defs/checks/clickhouse_serving_checks.py",
    "defs/checks/cn_a_gold_minute_checks.py",
    "defs/checks/dc_board_checks.py",
    "defs/checks/dc_board_silver_checks.py",
    "defs/checks/dc_daily_technical_checks.py",
    "defs/checks/dc_daily_technical_serving_checks.py",
    "defs/checks/dc_industry_hierarchy_checks.py",
    "defs/checks/etf_basic_checks.py",
    "defs/checks/etf_daily_checks.py",
    "defs/checks/etf_mins_checks.py",
    "defs/checks/idx_factor_pro_checks.py",
    "defs/checks/index_basic_checks.py",
    "defs/checks/index_daily_checks.py",
    "defs/checks/index_daily_nineturn_prod_core_checks.py",
    "defs/checks/index_global_checks.py",
    "defs/checks/index_mins_checks.py",
    "defs/checks/index_mins_gold_checks.py",
    "defs/checks/lake_root_health_checks.py",
    "defs/checks/major_index_mins_checks.py",
    "defs/checks/major_index_mins_gold_checks.py",
    "defs/checks/major_index_mins_technical_checks.py",
    "defs/checks/major_index_nineturn_checks.py",
    "defs/checks/market_breadth_checks.py",
    "defs/checks/market_major_indices_checks.py",
    "defs/checks/namechange_checks.py",
    "defs/checks/prod_clickhouse_serving_checks.py",
    "defs/checks/qfq_nineturn_checks.py",
    "defs/checks/stk_mins_checks.py",
    "defs/checks/stk_mins_qfq_macd_kdj_checks.py",
    "defs/checks/stk_nineturn_checks.py",
    "defs/checks/stock_basic_checks.py",
    "defs/checks/stock_daily_checks.py",
    "defs/checks/stock_daily_qfq_checks.py",
    "defs/checks/stock_daily_qfq_nineturn_prod_core_checks.py",
    "defs/checks/stock_daily_trend_channel_checks.py",
    "defs/checks/stock_identity_map_checks.py",
    "defs/checks/stock_lifecycle_checks.py",
    "defs/checks/stock_partition_checks.py",
    "defs/checks/stock_return_distribution_checks.py",
    "defs/checks/stock_suspend_confirmed_checks.py",
    "defs/checks/suspend_d_checks.py",
    "defs/checks/wealth_market_turnover_checks.py",
    "defs/corrections/__init__.py",
    "defs/corrections/suspend_full_day.py",
    "defs/corrections/suspend_timing.py",
    "defs/duckdb_connection.py",
    "defs/duckdb_sql.py",
    "defs/health/__init__.py",
    "defs/health/lake_root.py",
    "defs/io/__init__.py",
    "defs/io/cn_a_gold_minute_bars.py",
    "defs/io/cn_a_gold_minute_writer.py",
    "defs/io/etf_daily_raw_writer.py",
    "defs/io/etf_daily_silver_writer.py",
    "defs/io/idx_factor_pro_raw_writer.py",
    "defs/io/idx_factor_pro_silver_writer.py",
    "defs/io/major_index_mins_quality.py",
    "defs/io/major_index_mins_raw_writer.py",
    "defs/io/major_index_mins_silver_writer.py",
    "defs/io/major_index_mins_technical_writer.py",
    "defs/jobs/__init__.py",
    "defs/jobs/calendar_update.py",
    "defs/jobs/clickhouse_share_fact_market_breadth_update.py",
    "defs/jobs/daily_market_breadth.py",
    "defs/jobs/dc_board.py",
    "defs/jobs/dc_board_silver.py",
    "defs/jobs/dc_daily_technical.py",
    "defs/jobs/dc_daily_technical_repair.py",
    "defs/jobs/dc_daily_technical_serving.py",
    "defs/jobs/dc_industry_hierarchy.py",
    "defs/jobs/etf_basic_update.py",
    "defs/jobs/etf_daily.py",
    "defs/jobs/etf_mins_update.py",
    "defs/jobs/gold_major_index_mins_technical_daily_update.py",
    "defs/jobs/gold_stk_mins_qfq_macd_kdj_daily_update.py",
    "defs/jobs/gold_stk_mins_qfq_macd_kdj_repair.py",
    "defs/jobs/gold_stock_daily_qfq_factor_repair.py",
    "defs/jobs/gold_stock_daily_trend_channel_repair.py",
    "defs/jobs/gold_wealth_market_turnover_update.py",
    "defs/jobs/idx_factor_pro.py",
    "defs/jobs/index_basic_update.py",
    "defs/jobs/index_daily_nineturn_prod_core_sync.py",
    "defs/jobs/index_daily_update.py",
    "defs/jobs/index_global.py",
    "defs/jobs/index_mins.py",
    "defs/jobs/index_mins_gold.py",
    "defs/jobs/lake_root_health_check.py",
    "defs/jobs/major_index_mins.py",
    "defs/jobs/major_index_mins_gold.py",
    "defs/jobs/major_index_nineturn_update.py",
    "defs/jobs/market_major_indices_daily_update.py",
    "defs/jobs/namechange_update.py",
    "defs/jobs/prod_clickhouse_share_fact_market_breadth_sync.py",
    "defs/jobs/silver_dc_daily_repair.py",
    "defs/jobs/silver_index_daily_update.py",
    "defs/jobs/stk_mins_qfq_nineturn_update.py",
    "defs/jobs/stk_nineturn_update.py",
    "defs/jobs/stock_adj_factor_update.py",
    "defs/jobs/stock_basic_update.py",
    "defs/jobs/stock_daily_qfq_nineturn_prod_core_sync.py",
    "defs/jobs/stock_daily_qfq_nineturn_update.py",
    "defs/jobs/stock_daily_qfq_update.py",
    "defs/jobs/stock_daily_trend_channel_update.py",
    "defs/jobs/stock_daily_update.py",
    "defs/jobs/stock_identity_map_update.py",
    "defs/jobs/stock_mins_qfq_daily_update.py",
    "defs/jobs/stock_mins_qfq_factor_repair.py",
    "defs/jobs/stock_mins_raw_update.py",
    "defs/jobs/stock_mins_silver_update.py",
    "defs/jobs/stock_return_distribution_daily.py",
    "defs/jobs/suspend_update.py",
    "defs/major_index_nineturn.py",
    "defs/major_index_nineturn_integrity.py",
    "defs/namechange_timeline.py",
    "defs/nineturn_formula.py",
    "defs/notifications/__init__.py",
    "defs/notifications/feishu.py",
    "defs/ops/__init__.py",
    "defs/ops/dc_daily_technical_repair.py",
    "defs/ops/gold_stk_mins_qfq_macd_kdj_repair.py",
    "defs/ops/gold_stock_daily_qfq_factor_repair.py",
    "defs/ops/gold_stock_daily_trend_channel_repair.py",
    "defs/ops/silver_dc_daily_repair.py",
    "defs/ops/stock_mins_qfq_factor_repair.py",
    "defs/partitions.py",
    "defs/paths.py",
    "defs/prod_db/__init__.py",
    "defs/prod_db/etf_mins.py",
    "defs/prod_db/index_daily.py",
    "defs/prod_db/index_daily_nineturn.py",
    "defs/prod_db/index_mins.py",
    "defs/prod_db/stk_mins.py",
    "defs/prod_db/stk_mins_task_run.py",
    "defs/prod_db/stock_daily_qfq_nineturn.py",
    "defs/prod_db/wealth_market_turnover.py",
    "defs/prod_db/wealth_sector_hierarchy.py",
    "defs/qfq_nineturn.py",
    "defs/qfq_nineturn_integrity.py",
    "defs/resources.py",
    "defs/run_contracts/__init__.py",
    "defs/run_contracts/asset_column_schemas.py",
    "defs/run_contracts/asset_tags.py",
    "defs/run_contracts/cn_a_derived_minute_bars.py",
    "defs/run_contracts/column_schema.py",
    "defs/run_contracts/configs.py",
    "defs/run_contracts/cursor_payloads.py",
    "defs/run_contracts/cursors.py",
    "defs/run_contracts/dc_board.py",
    "defs/run_contracts/dc_daily_technical.py",
    "defs/run_contracts/dc_daily_technical_serving.py",
    "defs/run_contracts/etf_basic.py",
    "defs/run_contracts/etf_daily.py",
    "defs/run_contracts/etf_mins.py",
    "defs/run_contracts/idx_factor_pro.py",
    "defs/run_contracts/index_global.py",
    "defs/run_contracts/index_mins.py",
    "defs/run_contracts/major_index_mins.py",
    "defs/run_contracts/major_index_mins_technical.py",
    "defs/run_contracts/major_index_nineturn.py",
    "defs/run_contracts/metadata.py",
    "defs/run_contracts/qfq_nineturn.py",
    "defs/run_contracts/requests.py",
    "defs/run_contracts/run_keys.py",
    "defs/run_contracts/sensor_tags.py",
    "defs/run_contracts/silver_repair.py",
    "defs/run_contracts/stk_mins.py",
    "defs/schedules/__init__.py",
    "defs/schedules/lake_root_health.py",
    "defs/sensors/__init__.py",
    "defs/sensors/clickhouse_market_breadth_continuity_sensor.py",
    "defs/sensors/cn_a_gold_minute_sensor.py",
    "defs/sensors/cn_a_trade_day_sensor.py",
    "defs/sensors/dc_board_partition_sensor.py",
    "defs/sensors/dc_board_sensor.py",
    "defs/sensors/dc_board_silver_sensor.py",
    "defs/sensors/dc_daily_technical_repair_sensor.py",
    "defs/sensors/dc_daily_technical_sensor.py",
    "defs/sensors/dc_daily_technical_serving_sensor.py",
    "defs/sensors/etf_basic_sensor.py",
    "defs/sensors/etf_daily_sensor.py",
    "defs/sensors/etf_mins_partition_sensor.py",
    "defs/sensors/etf_mins_sensor.py",
    "defs/sensors/feishu_run_status_sensor.py",
    "defs/sensors/global_index_partition_sensor.py",
    "defs/sensors/gold_major_index_mins_technical_daily_update_job_sensor.py",
    "defs/sensors/gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py",
    "defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py",
    "defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py",
    "defs/sensors/gold_stock_daily_trend_channel_repair_job_sensor.py",
    "defs/sensors/gold_wealth_market_turnover_sensor.py",
    "defs/sensors/idx_factor_pro_partition_sensor.py",
    "defs/sensors/idx_factor_pro_sensor.py",
    "defs/sensors/index_daily_nineturn_prod_core_sensor.py",
    "defs/sensors/index_daily_raw_file_readiness.py",
    "defs/sensors/index_global_late_empty_sensor.py",
    "defs/sensors/index_global_retry_sensor.py",
    "defs/sensors/index_global_sensor.py",
    "defs/sensors/index_mins_gold_sensor.py",
    "defs/sensors/index_mins_partition_sensor.py",
    "defs/sensors/index_mins_sensor.py",
    "defs/sensors/index_trade_day_sensor.py",
    "defs/sensors/major_index_mins_gold_sensor.py",
    "defs/sensors/major_index_mins_partition_sensor.py",
    "defs/sensors/major_index_mins_sensor.py",
    "defs/sensors/major_index_nineturn_sensor.py",
    "defs/sensors/market_breadth_continuity_sensor.py",
    "defs/sensors/market_major_indices_daily_sensor.py",
    "defs/sensors/market_major_indices_input_readiness.py",
    "defs/sensors/prod_dc_daily_technical_sensor.py",
    "defs/sensors/raw_index_daily_update_job_sensor.py",
    "defs/sensors/readiness.py",
    "defs/sensors/silver_index_daily_sensor.py",
    "defs/sensors/silver_index_global_retry_sensor.py",
    "defs/sensors/silver_index_global_sensor.py",
    "defs/sensors/stk_mins_qfq_nineturn_sensor.py",
    "defs/sensors/stk_nineturn_sensor.py",
    "defs/sensors/stk_nineturn_trade_day_sensor.py",
    "defs/sensors/stock_adj_factor_sensor.py",
    "defs/sensors/stock_basic_sensor.py",
    "defs/sensors/stock_current_trade_day_sensor.py",
    "defs/sensors/stock_daily_qfq_nineturn_prod_core_sensor.py",
    "defs/sensors/stock_daily_qfq_nineturn_sensor.py",
    "defs/sensors/stock_daily_qfq_sensor.py",
    "defs/sensors/stock_daily_raw_repair.py",
    "defs/sensors/stock_daily_sensor.py",
    "defs/sensors/stock_daily_trend_channel_sensor.py",
    "defs/sensors/stock_daily_trend_channel_trade_day_sensor.py",
    "defs/sensors/stock_identity_map_sensor.py",
    "defs/sensors/stock_mins_qfq_daily_sensor.py",
    "defs/sensors/stock_mins_qfq_factor_repair_sensor.py",
    "defs/sensors/stock_mins_raw_sensor.py",
    "defs/sensors/stock_mins_silver_sensor.py",
    "defs/sensors/stock_mins_silver_trade_day_sensor.py",
    "defs/sensors/stock_mins_trade_day_sensor.py",
    "defs/sensors/stock_namechange_sensor.py",
    "defs/sensors/stock_return_distribution_continuity_sensor.py",
    "defs/sensors/stock_trade_day_sensor.py",
    "defs/sensors/suspend_d_sensor.py",
    "defs/stk_mins_qfq.py",
    "defs/stk_mins_qfq_factor_repair.py",
    "defs/stk_mins_qfq_macd_kdj.py",
    "defs/stk_nineturn_contract.py",
    "defs/stock_daily_qfq.py",
    "defs/stock_daily_trend_channel.py",
    "defs/stock_suspend_confirmed_contract.py",
    "defs/tushare_api_io.py",
    "defs/tushare_request_policy.py",
    "defs/wealth_market_turnover_contract.py",
    "seeds/__init__.py",
    "seeds/basic/__init__.py",
    "seeds/basic/stock_identity_mappings.py",
    "seeds/board/__init__.py",
    "seeds/board/eastmoney_dc_industry_hierarchy.py",
    "seeds/market/__init__.py",
    "seeds/market/major_indices.py",
    "seeds/quote/__init__.py",
    "seeds/quote/stk_mins_price_corrections.py",
    "source_readiness/__init__.py",
    "source_readiness/tushare/__init__.py",
    "source_readiness/tushare/index_daily.py",
    "source_readiness/tushare/stock_daily.py",
    "utils/__init__.py",
    "utils/dg_log_helper.py",
)


CONSUMER_SUITES = {
    "test_suspend_d_checks.py": 7,
    "test_stock_daily_raw_checks.py": 22,
    "test_stock_daily_raw_repair.py": 8,
    "test_stock_daily_freshness_guard.py": 5,
    "test_stk_mins_silver_m5b_contracts.py": 20,
    "test_stk_mins_silver_m5e_job_contracts.py": 2,
    "test_stk_mins_lake_readiness.py": 20,
    "test_stk_mins_silver_m6_history.py": 8,
    "test_stk_mins_silver_replace_from_raw.py": 7,
    "test_stk_mins_bse_history_recovery.py": 26,
    "test_stk_mins_silver_strict_audit.py": 2,
    "test_stock_mins_daily_continuity_sensors.py": 26,
    "test_stk_mins_silver_m6g_sensor_contracts.py": 8,
    "test_asset_check_incremental_governance.py": 6,
    "test_asset_governance_contracts.py": 12,
    "test_run_contract_static_gates.py": 112,
}


def consumer_batches(suite: str):
    """Collect every method in a fixed suite; never select away a failing case."""
    tree = ast.parse((PROJECT / "tests" / suite).read_text())
    cases = tuple(
        f"{cls.name}::{node.name}"
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )
    if len(cases) != CONSUMER_SUITES[suite] or len(set(cases)) != len(cases):
        raise RuntimeError(f"consumer_case_inventory_changed:{suite}")
    return tuple(
        (
            f"G-regression:{suite}:{offset // 8 + 1}",
            len(cases[offset : offset + 8]),
            cases[offset : offset + 8],
        )
        for offset in range(0, len(cases), 8)
    )


REGRESSION_SUITES = {
    **dict.fromkeys(CONSUMER_SUITES),
    "root-guard": (("G-retirement", 13, (
        "test_retired_console_has_no_versioned_or_new_source_files",
        "test_current_python_sources_do_not_import_retired_backend",
        "test_import_guard_rejects_retired_import_forms",
        "test_import_guard_preserves_current_modules_and_historical_text",
        "test_current_runtime_and_versioned_config_have_no_legacy_console_or_kopia_reference",
        "test_current_lake_consumers_and_clickhouse_tools_are_present",
    )),),
    "test_stock_suspend_confirmed_bootstrap.py": (
        ("B-plan", 12, ("test_complete_comparison_is_readonly_and_uses_shared_normalization", "test_plan_rejections",
                        "test_year_batch_boundary_is_bounded")),
        ("B-compare", 11, ("test_comparison_detects_content_and_partition_errors", "test_input_drift_refused",
                           "test_comparison_counts_all_differences_but_limits_samples")),
        ("B-report", 6, ("test_report_scope_rejected", "test_report_is_immutable_and_not_implicitly_created")),
        ("B-publish", 12, ("test_file_publication_states", "test_publication_resume",
                            "test_missing_candidate_and_checkpoint_recognizes_correct_target")),
        ("B-boundaries", 16, ("test_unsafe_publication_refused", "test_cli_help_and_bad_arguments_have_no_io")),
        ("B-cli", 5, ("test_cli_readonly_full_chain", "test_cli_save_and_confirmed_publish_are_separate",
                       "test_cli_wrong_hash_does_not_connect")),
        ("E-roundtrip", 11, ("test_event_roundtrip_and_existing_prefix", "test_event_reuses_daily_checks_without_token",
                              "test_event_uncertainty_and_recovery")),
        ("E-conflicts", 13, ("test_event_conflicts_never_write", "test_event_cli_readonly_and_apply")),
        ("B07-instance", 10, ("test_event_native_instance_construction",)),
        ("E-resume-boundaries", 8, ("test_event_additional_resume_boundaries",)),
    ),
    "test_duckdb_connection.py": (
        ("B06-existing-contract", 6, (
            "DuckDBConnectionTests::test_default_settings_are_fixed_contract",
            "DuckDBConnectionTests::test_connect_configured_duckdb_applies_runtime_settings",
            "DuckDBConnectionTests::test_connect_configured_duckdb_rejects_invalid_temp_directory",
            "DuckDBConnectionTests::test_duckdb_resource_uses_configured_connection",
            "DuckDBConnectionTests::test_duckdb_resource_exits_connection_on_consumer_error",
            "DuckDBConnectionTests::test_duckdb_resource_propagates_connection_factory_error",
        )),
        ("B06-paths", 8, (
            "test_existing_no_spill_rejects_paths_before_connect",
            "test_unknown_policy_rejected_before_any_path_io",
        )),
        ("B06-real-settings", 13, (
            "test_existing_no_spill_uses_real_connection_without_directory_writes",
            "test_explicit_managed_preserves_config_and_creates_directory",
            "test_real_connection_closed_on_consumer_error",
            "test_setting_mismatch_closes_real_connection_without_fallback",
            "test_invalid_settings_do_not_connect",
            "test_memory_exhaustion_does_not_enable_spill_or_retry",
            "test_connection_failure_propagates_without_retry",
        )),
    ),
    "test_suspend_d_sensor.py": (
        ("R-existing-contract", 8, (
            "SuspendDSensorTests::test_job_and_sensor_names_follow_split_rule",
            "SuspendDSensorTests::test_sensor_tags_are_layer_specific",
            "SuspendDSensorTests::test_asset_descriptions_explain_business_purpose",
            "SuspendDSensorTests::test_suspend_d_stdout_events_are_small_and_named",
            "SuspendDSensorTests::test_human_materialization_metadata_uses_namespaced_operator_fields",
            "SuspendDSensorTests::test_existing_suspend_d_check_names_are_not_renamed",
        )),
        ("R-existing-selection", 10, (
            "SuspendDSensorTests::test_raw_sensor_submits_run_when_raw_missing",
            "SuspendDSensorTests::test_raw_sensor_skips_registered_gap_before_materialization_scan",
            "SuspendDSensorTests::test_raw_sensor_does_not_rerun_materialized_partition",
            "SuspendDSensorTests::test_silver_sensor_submits_only_when_raw_ready_and_silver_missing",
            "SuspendDSensorTests::test_silver_sensor_skips_registered_gap_before_readiness_scan",
            "SuspendDSensorTests::test_silver_sensor_skips_when_raw_missing_or_checks_not_ready",
            "SuspendDSensorTests::test_silver_sensor_does_not_rerun_materialized_partition",
        )),
    ),
    "test_stock_suspend_confirmed_integration.py": (
        ("D-actual-job", 10, ("test_actual_silver_job", "test_actual_catalog_registration")),
    ),
    "test_stock_suspend_confirmed_readiness.py": (
        ("R-file-publication", 11, ("test_physical_gate", "test_publication_gate")),
        ("R-latest-checks", 11, ("test_latest_checks_gate",)),
        ("R-sensor", 8, ("test_sensor_bounded_gate",)),
    ),
    "test_stock_suspend_confirmed_merge.py": (
        ("M-add-conflict", 9, ("test_add_missing", "test_raw_duplicates", "test_conflict",
                               "test_unmatched_raw", "test_empty")),
        ("M-override", 7, ("test_replace_confirmed", "test_original_override_rows")),
        ("M-order-stats", 10, ("test_timing_corrections", "test_timing_overlap", "test_selected_dates",
                                "test_no_date_filter", "test_conflict_stats", "test_bounded_classification_samples",
                                "test_null_conflict_semantics", "test_pure_builders")),
        ("M-input-boundaries", 16, ("test_relation_names", "test_runner_selection_rejected")),
    ),
    "test_stock_suspend_confirmed_writer.py": (
        ("W-success", 9, ("test_writer_literal_results", "test_writer_rebuild_and_reuse",
                           "test_writer_public_signature", "test_writer_asset_dependency")),
        ("W-reject", 11, ("test_writer_conflict", "test_writer_wrong_raw_date", "test_writer_invalid_fixed",
                           "test_writer_candidate_failure")),
        ("W-resume", 12, ("test_writer_resume", "test_writer_committed_input_drift",
                           "test_writer_prepared_drift")),
        ("W-checkpoint", 13, ("test_writer_corrupt_checkpoint", "test_writer_committed_target_changed",
                               "test_writer_checkpoint_write_failure", "test_writer_orphan_candidate")),
        ("W-identity", 13, ("test_writer_load_drift", "test_writer_prepared_window_drift",
                             "test_writer_invalid_paths")),
    ),
}


def source_files_for_scope(scope: str) -> tuple[str, ...]:
    if scope == "root-guard":
        return RESOURCE_SOURCE_FILES
    if scope == "consumer":
        return CONSUMER_SOURCE_FILES
    additions = {"isolation": (), "adapter": ADAPTER_SOURCE_FILES,
                 "regression": tuple(dict.fromkeys(MERGE_SOURCE_FILES + ADAPTER_SOURCE_FILES + WRITER_SOURCE_FILES + INTEGRATION_SOURCE_FILES + (
                     "defs/bootstrap/__init__.py", "defs/bootstrap/stock_suspend_confirmed.py",
                     "defs/bootstrap/stock_suspend_confirmed_cli.py",
                     "defs/bootstrap/stock_suspend_confirmed_events.py",
                 )))}
    if scope not in additions:
        raise ValueError("invalid_scope")
    return RESOURCE_SOURCE_FILES + additions[scope]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy_for(root: Path, *, scope: str = "isolation") -> str:
    """Allow exact source files and import directory objects, never repo subtrees."""
    package_init = PROJECT / "tests/__init__.py"
    if package_init.is_symlink() or package_init.read_bytes() != b"\n":
        raise RuntimeError("tests_package_init_changed: re-audit before importing")
    try:
        (PROJECT / "__init__.py").lstat()
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("project_package_marker_present: re-audit before importing")
    source_files = [SOURCE / name for name in source_files_for_scope(scope)]
    files = [*source_files, SUPPORT, TEST, Path(__file__).resolve(), package_init]
    if scope == "adapter":
        files.extend(PROJECT / f"tests/test_stock_suspend_confirmed_{name}.py" for name in ("contracts", "dagster"))
    elif scope in ("regression", "consumer"):
        files.extend(PROJECT / "tests" / name for name in REGRESSION_SUITES if name != "root-guard")
    if scope == "consumer":
        files.append(SOURCE / "seeds/quote/stk_mins_price_corrections.cn_a.csv")
        files.append(SOURCE / "seeds/board/eastmoney_dc_industry_hierarchy.cn_a.v1.csv")
        files.append(SOURCE / "seeds/board/eastmoney_dc_industry_hierarchy.cn_a.v1.source.png")
        files.append(PROJECT.parent / "docs/design/dagster-event-history-retention-governance-plan.md")
        files.append(PROJECT / "tests/test_asset_check_event_retention.py")
    if scope == "root-guard":
        repo = PROJECT.parents[1]
        inventory_paths = [Path(name) for name in json.loads((root / "allowed/source-inventory.json").read_text())]
        # Exact source paths, not a recursive repository or .git permission.
        files.extend(path for path in inventory_paths if path.suffix in (
            ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".toml", ".yaml", ".yml", ".sh",
        ))
        files.append(repo / "tests/architecture/test_lake_console_retirement_guardrails.py")
    directories = {PROJECT, PROJECT / "src", PROJECT / "tests"}
    for path in source_files:
        directories.update(p for p in path.parents if p == SOURCE or SOURCE in p.parents)
    if scope == "root-guard":
        directories.update((repo / "tests", repo / "tests/architecture"))
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Source allowlist must contain regular files: {path}")
    literals = "\n".join(f"  (literal {json.dumps(str(p))})" for p in sorted(set(files) | directories))
    metadata_only = ""
    if scope == "root-guard":
        presence_only = tuple(repo / name for name in (
            "src/foundation/clients/local_lake/stock_mins_reader.py",
            "src/foundation/clients/local_lake/major_index_mins_reader.py",
            "src/foundation/clients/local_lake/stock_nine_turn_reader.py",
            "src/foundation/clients/local_lake/index_nine_turn_reader.py",
            "src/foundation/clients/local_lake/major_index_turnover_reader.py",
            "src/foundation/clients/local_lake/stock_daily_trend_channel_reader.py",
            "src/ops/models/ops/dataset_status_snapshot.py",
            "lake_console/bin/lake-clickhouse-start",
            "lake_console/bin/lake-prod-clickhouse-tunnel",
            "lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day_ranges.csv",
        ))
        metadata_only = "(allow file-read-metadata\n" + "\n".join(
            f"  (literal {json.dumps(str(path))})" for path in presence_only
        ) + ")\n"
    # The first block preserves the approved I01/I02 runtime/device permissions.
    return f'''(version 1)
(allow default)
(deny file-read* file-write* network*)
(allow file-read*
  (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share")
  (subpath "/Users/congming/miniconda3/bin")
  (subpath "/Users/congming/miniconda3/lib")
  (subpath "{PROJECT}/.venv")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* file-write* (subpath "{root}/allowed"))
(allow file-read-metadata
  (literal "/private") (literal "/private/tmp") (literal "/tmp")
  (literal "{root}"))
(allow file-read*
{literals})
(allow file-read-metadata (literal "{PROJECT}/__init__.py"))
{metadata_only}
'''


def inventory(directory: Path) -> list[dict]:
    result = []
    for path in sorted(directory.rglob("*")):
        st = path.lstat()
        result.append({
            "path": str(path.relative_to(directory)), "dev": st.st_dev,
            "inode": st.st_ino, "mode": st.st_mode, "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": digest(path) if path.is_file() and not path.is_symlink() else None,
        })
    return result


def create_isolation_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="stock-suspend-isolated-", dir="/private/tmp"))
    allowed, denied = root / "allowed", root / "denied-fixture"
    allowed.mkdir()
    denied.mkdir()
    return root


def workspace_size(roots: tuple[Path, ...]) -> int:
    """Count regular files once, without following pytest's replaceable aliases."""
    size = 0
    for root in roots:
        for path in root.rglob("*"):
            try:
                observed = path.lstat()
            except FileNotFoundError:
                continue  # A transient test file was removed during the walk.
            if stat.S_ISREG(observed.st_mode):
                size += observed.st_size
    return size


def run_isolation_batch(batch: str, expected_count: int, case_names: tuple[str, ...]) -> int:
    root = create_isolation_root()
    allowed = root / "allowed"
    with ExitStack() as endpoints:
        listeners = {}
        if batch == "I06":
            for kind, family in (("tcp", socket.AF_INET), ("unix", socket.AF_UNIX)):
                listener = endpoints.enter_context(socket.socket(family, socket.SOCK_STREAM))
                listener.settimeout(1)
                listener.bind(("127.0.0.1", 0) if kind == "tcp" else str(allowed / "network.sock"))
                listener.listen(1)
                listeners[kind] = listener
        return run_isolation_child(root, batch, expected_count, case_names, listeners)


def verify_parent_network_endpoints(listeners: dict) -> dict:
    """A live synthetic endpoint control, not a service or a database probe."""
    observed = {}
    for kind, listener in listeners.items():
        if select.select([listener], [], [], 0)[0]:
            raise RuntimeError(f"unexpected_child_network_connection:{kind}")
        with socket.socket(listener.family, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(listener.getsockname())
            with listener.accept()[0] as accepted:
                accepted.settimeout(1)
                client.sendall(b"x")
                assert accepted.recv(1) == b"x"
                accepted.sendall(b"y")
                assert client.recv(1) == b"y"
        observed[kind] = {"reachable": True, "request_bytes": 1, "response_bytes": 1}
    return observed


def run_isolation_child(root: Path, batch: str, expected_count: int,
                        case_names: tuple[str, ...], listeners: dict, *,
                        startup_probe: str | None = None, batch_deadline: float | None = None,
                        budget_roots: tuple[Path, ...] = (), scope: str = "isolation",
                        test_file: Path = TEST) -> int:
    allowed, denied = root / "allowed", root / "denied-fixture"
    network_targets = {kind: listener.getsockname() for kind, listener in listeners.items()}
    network_before = verify_parent_network_endpoints(listeners)
    (denied / "sentinel.txt").write_text("synthetic denied resource fixture\n")
    policy = allowed / "capability.sb"
    policy.write_text(policy_for(root, scope=scope))
    bootstrap = allowed / "bootstrap.py"
    source = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('stock_suspend_confirmed_test_support', {str(SUPPORT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
    )
    selected_policy = policy
    if startup_probe is None:
        source += (
            f"raise SystemExit(module.run({str(root)!r}, {digest(policy)!r}, {str(test_file)!r}, "
            f"batch={batch!r}, case_names={case_names!r}, expected_count={expected_count!r}, "
            f"network_targets={network_targets!r}, scope={scope!r}))\n"
        )
    else:
        if startup_probe not in STARTUP_PROBES:
            raise ValueError("unknown_startup_probe")
        source = "print('I07_PAYLOAD_STARTED', flush=True)\n" + source
        fixture = prepare_startup_fixture(root, startup_probe)
        source += f"raise SystemExit(module.probe_startup_gate({startup_probe!r}, {str(root)!r}, {digest(policy)!r}, {str(fixture)!r}))\n"
        if startup_probe == "policy_missing":
            selected_policy = allowed / "missing.sb"
        elif startup_probe == "policy_invalid":
            selected_policy = allowed / "invalid.sb"
            selected_policy.write_text("(version 1)\n(I07_INVALID_PROFILE)\n")
        elif startup_probe == "selfcheck_failed_stale":
            (allowed / "pytest-result.json").write_text(json.dumps({
                "passed": True, "completed": 1, "failures": 0, "synthetic_stale": True,
            }) + "\n")
    bootstrap.write_text(source)
    argv = [
        "/opt/homebrew/bin/uv", "run", "--offline", "--no-sync", "--no-env-file",
        "--no-config", "--no-python-downloads", "--cache-dir", str(allowed / "uv-cache"),
        "/usr/bin/sandbox-exec", "-f", str(selected_policy), str(PROJECT / ".venv/bin/python"),
        "-I", "-B", str(bootstrap),
    ]
    env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8",
           "TMPDIR": str(allowed), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    before = inventory(denied)
    started = time.monotonic()
    report = {
        "scope": scope, "implemented_slice": batch,
        "case_names": list(case_names), "expected_count": expected_count,
        "startup_probe": startup_probe,
        "expected_resource_gate": startup_probe in (None, "collection_allowed"),
        "network_targets": network_targets, "network_before": network_before,
        "root": str(root), "cwd": str(PROJECT), "argv": argv, "env_keys": sorted(env),
        "policy_sha256": digest(policy), "policy": policy.read_text(),
        "selected_policy": str(selected_policy),
        "selected_policy_text": selected_policy.read_text() if selected_policy.exists() else None,
        "test_source_sha256": {str(p): digest(p) for p in (Path(__file__), SUPPORT, TEST, test_file)},
        "source_files": list(source_files_for_scope(scope)),
        "source_sha256": {name: digest(SOURCE / name) for name in source_files_for_scope(scope)},
        "before": before, "passed": False,
    }
    report_path = allowed / "resource-result.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"starting": True, **report}), flush=True)
    process = subprocess.Popen(argv, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               close_fds=True, start_new_session=True)
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    stop_reason = None

    def finish_child(exc_type, error, traceback):
        # The parent owns this process group; do not leave it running on a monitor error.
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
        if exc_type is not None:
            report.update(passed=False, exit_code=process.returncode, stop_reason="parent_monitor_error",
                          monitor_error_type=exc_type.__name__, monitor_error=str(error),
                          elapsed_ms=round(1000 * (time.monotonic() - started)),
                          child_reaped=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
        return False

    with ExitStack() as lifetime, selectors.DefaultSelector() as selector:
        lifetime.push(finish_child)
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            if stop_reason is None:
                if batch_deadline is not None and time.monotonic() > batch_deadline:
                    stop_reason = "batch_timeout_60s"
                elif time.monotonic() - started > (30 if startup_probe else 60):
                    stop_reason = "case_timeout_30s" if startup_probe else "batch_timeout_60s"
                elif workspace_size(budget_roots or (root,)) > 100 * 1024**2:
                    stop_reason = "workspace_budget_100MiB"
                if stop_reason and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            for key, _ in selector.select(0.1):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if len(outputs[key.data]) + len(data) > 65536:
                    if stop_reason is None:
                        stop_reason = f"{key.data}_budget_64KiB"
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                else:
                    outputs[key.data].extend(data)
                    print(data.decode(errors="replace"), end="", flush=True)
    code = process.wait(timeout=5)
    network_after = verify_parent_network_endpoints(listeners)
    after = inventory(denied)
    result = allowed / "pytest-result.json"
    observed = json.loads(result.read_text()) if result.is_file() else None
    passed = code == 0 and stop_reason is None and before == after and observed is not None
    passed = passed and observed.get("passed") is True and observed.get("completed") == expected_count
    resource_gate_passed = passed
    probe_evidence = None
    if startup_probe is not None:
        probe_evidence = evaluate_startup_probe(root, startup_probe, code, outputs, observed)
        passed = stop_reason is None and before == after and probe_evidence["passed"] \
            and resource_gate_passed == (startup_probe == "collection_allowed")
    report.update({"passed": passed, "resource_gate_passed": resource_gate_passed,
                   "startup_evidence": probe_evidence, "after": after, "denied_unchanged": before == after,
                   "network_after": network_after,
                   "exit_code": code, "stop_reason": stop_reason, "pytest": observed,
                   "elapsed_ms": round(1000 * (time.monotonic() - started)),
                   **{name: data.decode(errors="replace") for name, data in outputs.items()}})
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"batch": batch, "passed": passed, "report": str(report_path)}), flush=True)
    return 0 if passed else 1


def prepare_startup_fixture(root: Path, case: str) -> Path:
    """Create only fixed synthetic collection sources; never a business test."""
    if case not in ("collection_allowed", "collection_denied", "skip", "xfail"):
        return TEST
    allowed = root / "allowed"
    (allowed / "sentinel.txt").write_text("synthetic denied resource fixture\n")
    target = (root / "denied-fixture" if case == "collection_denied" else allowed) / "sentinel.txt"
    source = (
        "import json\nfrom pathlib import Path\nimport pytest\n"
        "from stock_suspend_confirmed_test_support import require_isolated_context\n"
        "allowed = require_isolated_context()\n"
        "(allowed / 'collection-entered.txt').write_text('synthetic')\n"
        f"target = Path({str(target)!r})\n"
        "try:\n    assert target.read_bytes() == b'synthetic denied resource fixture\\n'\n"
        "except OSError as error:\n"
        "    (allowed / 'collection-denial.json').write_text(json.dumps({'errno': error.errno, 'target': str(target)}))\n"
        "    raise\n"
        "(allowed / 'collection-finished.txt').write_text('synthetic')\n"
    )
    if case == "skip":
        source += "@pytest.mark.skip(reason='I07_synthetic_skip')\n"
    source += "def test_body():\n"
    if case == "xfail":
        source += "    pytest.xfail('I07_synthetic_xfail')\n"
    source += "    (allowed / 'test-body.txt').write_text('synthetic')\n"
    fixture = allowed / "test_startup_fixture.py"
    fixture.write_text(source)
    return fixture


def evaluate_startup_probe(root: Path, case: str, code: int, outputs: dict, observed) -> dict:
    import errno

    allowed = root / "allowed"
    stdout, stderr = (outputs[name].decode(errors="replace") for name in ("stdout", "stderr"))
    proof_path = allowed / "startup-proof.json"
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else None
    if case.startswith("policy_") and case != "policy_mismatch":
        reason = (str(allowed / "missing.sb") in stderr and "No such file or directory" in stderr) \
            if case == "policy_missing" else "I07_INVALID_PROFILE" in stderr and "unbound variable" in stderr
        passed = code > 0 and reason and "I07_PAYLOAD_STARTED" not in stdout and proof is None and observed is None
    elif case in ("guard_missing", "guard_late", "policy_mismatch", "selfcheck_failed_stale"):
        reasons = {"guard_missing": "isolation_not_initialized_before_collection",
                   "guard_late": "protection_loaded_too_late", "policy_mismatch": "policy_mismatch",
                   "selfcheck_failed_stale": "synthetic_self_check_failed"}
        passed = code == 1 and proof is not None and proof.get("reason") == reasons[case] \
            and proof.get("context_initialized") is False \
            and proof.get("loaded_modules") == (["pytest"] if case == "guard_late" else [])
        passed = passed and (observed == {"passed": True, "completed": 1, "failures": 0, "synthetic_stale": True}
                             if case == "selfcheck_failed_stale" else observed is None)
    else:
        entered = (allowed / "collection-entered.txt").exists()
        finished = (allowed / "collection-finished.txt").exists()
        body = (allowed / "test-body.txt").exists()
        passed = entered and proof is not None and proof.get("business_modules") == [] and observed is not None
        if case == "collection_allowed":
            passed = passed and code == 0 and finished and body and observed.get("passed") is True \
                and observed.get("completed") == 1
        elif case == "collection_denied":
            denial_path = allowed / "collection-denial.json"
            denial = json.loads(denial_path.read_text()) if denial_path.exists() else {}
            passed = passed and code in (2, 4) and not finished and not body \
                and observed.get("passed") is False and observed.get("completed") == 0 \
                and denial.get("errno") in (errno.EPERM, errno.EACCES) \
                and denial.get("target") == str(root / "denied-fixture/sentinel.txt")
            proof = {**(proof or {}), "denial": denial}
        else:
            passed = passed and code == 0 and finished and not body and observed.get("passed") is False \
                and observed.get("completed") == 0 and observed.get("failures") == 1 \
                and ("1 skipped" if case == "skip" else "1 xfailed") in stdout
        proof = {**(proof or {}), "collection_entered": entered, "collection_finished": finished,
                 "test_body_executed": body}
    return {"passed": bool(passed), "case": case, "proof": proof}


def run_startup_gate_batch() -> int:
    import io
    from contextlib import redirect_stderr
    from unittest.mock import patch

    root = create_isolation_root()
    roots = [root]
    started = time.monotonic()
    results = []
    report_path = root / "allowed/startup-result.json"

    def save_report(passed=False):
        report_path.write_text(json.dumps({
            "slice": "I07", "passed": passed, "expected_count": 15, "completed": len(results),
            "elapsed_ms": round(1000 * (time.monotonic() - started)),
            "roots": [str(path) for path in roots], "results": results,
        }, indent=2) + "\n")

    save_report()
    for name, args, reason in (
        ("scope_missing", [], "required: --scope"),
        ("scope_value_missing", ["--scope"], "expected one argument"),
        ("scope_unknown", ["--scope", "unknown"], "invalid choice"),
        ("wrong_cwd", ["--scope", "adapter"], "Run from"),
        ("scope_extra", ["--scope", "isolation", "-k", "synthetic"], "unrecognized arguments"),
    ):
        errors = io.StringIO()
        with ExitStack() as guards:
            guards.enter_context(patch.object(sys, "argv", [str(Path(__file__)), *args]))
            guards.enter_context(redirect_stderr(errors))
            if name == "wrong_cwd":
                guards.enter_context(patch.object(Path, "cwd", return_value=root))
            spies = [guards.enter_context(patch.object(owner, key, side_effect=AssertionError(key)))
                     for owner, key in ((tempfile, "mkdtemp"), (Path, "mkdir"), (subprocess, "Popen"))]
            try:
                main()
            except SystemExit as error:
                passed = error.code == 2 and reason in errors.getvalue() and not any(spy.called for spy in spies)
            else:
                passed = False
        results.append({"case": name, "passed": passed, "argv": args, "stderr": errors.getvalue(),
                        "mkdir_or_process_calls": sum(spy.call_count for spy in spies)})
        save_report()
        print(json.dumps(results[-1]), flush=True)
        if not passed:
            return 1
    for case in STARTUP_PROBES:
        if time.monotonic() - started > 60:
            save_report()
            return 1
        child_root = create_isolation_root()
        assert child_root not in roots
        roots.append(child_root)
        code = run_isolation_child(child_root, f"I07:{case}", 1, ("test_body",), {},
                                   startup_probe=case, batch_deadline=started + 60, budget_roots=tuple(roots))
        results.append({"case": case, "passed": code == 0,
                        "report": str(child_root / "allowed/resource-result.json")})
        save_report()
        if code:
            return 1
    save_report(passed=True)
    print(json.dumps({"batch": "I07", "passed": True, "completed": len(results), "report": str(report_path)}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("isolation", "adapter", "regression"), required=True)
    parser.add_argument("--suite", choices=tuple(REGRESSION_SUITES))
    args = parser.parse_args()
    if args.scope == "regression" and args.suite is None:
        parser.error("regression requires --suite")
    if args.scope != "regression" and args.suite is not None:
        parser.error("--suite is only allowed with regression")
    if Path.cwd() != PROJECT:
        parser.error(f"Run from {PROJECT}")
    if args.scope == "regression":
        is_consumer = args.suite in CONSUMER_SUITES
        batches = consumer_batches(args.suite) if is_consumer else REGRESSION_SUITES[args.suite]
        scope = "root-guard" if args.suite == "root-guard" else "consumer" if is_consumer else "regression"
        test_file = PROJECT.parents[1] / "tests/architecture/test_lake_console_retirement_guardrails.py" if args.suite == "root-guard" else PROJECT / "tests" / args.suite
        if scope == "root-guard":
            repo = PROJECT.parents[1]
            names = subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=repo,
            ).decode().split("\0")
            paths = sorted({repo / name for name in names if name and (repo / name).is_file()})
            if any(path.is_symlink() for path in paths):
                raise RuntimeError("root_guard_symlink_requires_review")
            # All original assertions run over each disjoint source slice. Their
            # union is exactly the frozen Git inventory; no file is filtered out.
            _, expected, cases = batches[0]
            for offset in range(0, len(paths), 1000):
                root = create_isolation_root()
                (root / "allowed/source-inventory.json").write_text(json.dumps([str(path) for path in paths[offset:offset + 1000]]))
                if run_isolation_child(root, f"G-retirement:{offset // 1000 + 1}", expected, cases, {}, scope=scope, test_file=test_file):
                    return 1
            print(json.dumps({"regression_suite_passed": "root-guard", "source_count": len(paths), "logical_cases": expected}), flush=True)
            return 0
        for batch, expected, cases in batches:
            if run_isolation_child(create_isolation_root(), batch, expected, cases, {}, scope=scope,
                                   test_file=test_file):
                return 1
        print(json.dumps({"regression_suite_passed": args.suite, "S1_complete": False,
                          "writer_executed": args.suite in ("test_stock_suspend_confirmed_writer.py", "test_stock_suspend_confirmed_integration.py", "test_stock_suspend_confirmed_bootstrap.py"),
                          "identity_profile": "synthetic", "formal_writer_executed": False,
                          "S2_executed": False}), flush=True)
        return 0
    if args.scope == "adapter":
        for batch, file_kind, expected, cases in ADAPTER_BATCHES:
            if run_isolation_child(create_isolation_root(), batch, expected, cases, {}, scope="adapter",
                                   test_file=PROJECT / f"tests/test_stock_suspend_confirmed_{file_kind}.py"):
                return 1
        print(json.dumps({"synthetic_adapter_passed": True, "S1_complete": False, "S2_executed": False}), flush=True)
        return 0
    for batch, expected_count, case_names in ISOLATION_BATCHES:
        if run_isolation_batch(batch, expected_count, case_names) != 0:
            return 1
    if run_startup_gate_batch() != 0:
        return 1
    if run_isolation_batch("I08", 3, (
        "test_i08_readonly_input_has_no_side_effects", "test_i08_health_probe_side_effects",
    )) != 0:
        return 1
    print(json.dumps({"I03_I04_I05_I06_I07_I08_passed": True,
                      "adapter_executed": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
