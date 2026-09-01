import ast
from pathlib import Path

import pytest

from orchestrator.defs.catalog import (
    ComputeEngine,
    EventPolicy,
    IngestionSource,
    PartitionModel,
    PartitionModelFamily,
    PartitionPhysicalLayout,
    WritePolicy,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.catalog.name_mapping import DATASET_CHINESE_NAMES
from orchestrator.defs.partitions import (
    cn_a_stock_daily_trend_channel_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
    GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
)


def test_schema_and_chinese_names_match_the_frozen_contract() -> None:
    assert [column.name for column in GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA] == [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "short_upper",
        "short_lower",
        "short_position",
        "short_state",
        "long_upper",
        "long_lower",
        "long_position",
        "long_state",
        "combined_state",
        "formula_version",
    ]
    assert [column.name for column in GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA] == [
        "ts_code",
        "trade_date",
        "state_source_trade_date",
        "observed_on_partition",
        "short_upper_raw",
        "short_lower_raw",
        "short_state",
        "long_upper_raw",
        "long_lower_raw",
        "long_state",
        "combined_state",
        "formula_version",
    ]
    assert all(column.description for column in GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA)
    assert all(
        column.description for column in GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    )
    assert DATASET_CHINESE_NAMES["stock_daily_trend_channel"] == (
        "股票日线前复权趋势通道"
    )
    assert DATASET_CHINESE_NAMES["stock_daily_trend_channel_state"] == (
        "股票日线前复权趋势通道状态"
    )


def test_formal_and_run_scoped_staging_paths_are_isolated() -> None:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    staging_root = Path(DEFAULT_LAKE_STAGING_ROOT)

    assert gold_stock_daily_trend_channel_path(
        lake_root, "2026-08-31"
    ) == lake_root / (
        "gold/indicator/stock_daily_trend_channel/"
        "trade_date=2026-08-31/part-000.parquet"
    )
    assert gold_stock_daily_trend_channel_state_path(
        lake_root, "2026-08-31"
    ) == lake_root / (
        "gold/indicator/stock_daily_trend_channel_state/"
        "trade_date=2026-08-31/part-000.parquet"
    )
    assert gold_stock_daily_trend_channel_staging_path(
        staging_root,
        "run-123",
        "2026-08-31",
    ) == staging_root / (
        "gold/indicator/stock_daily_trend_channel/"
        "run_id=run-123/trade_date=2026-08-31/part-000.parquet"
    )
    assert gold_stock_daily_trend_channel_state_staging_path(
        staging_root,
        "run-123",
        "2026-08-31",
    ) == staging_root / (
        "gold/indicator/stock_daily_trend_channel_state/"
        "run_id=run-123/trade_date=2026-08-31/part-000.parquet"
    )


@pytest.mark.parametrize("run_id", ["", " ", ".", "..", "a/b", "a\\b"])
def test_staging_path_rejects_unsafe_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError):
        gold_stock_daily_trend_channel_staging_path(
            Path(DEFAULT_LAKE_STAGING_ROOT),
            run_id,
            "2026-08-31",
        )


@pytest.mark.parametrize(
    "partition_key",
    ["", "20260831", "2026-02-30", "2026-08-31/next", "../2026-08-31"],
)
def test_paths_reject_non_iso_partition_keys(partition_key: str) -> None:
    with pytest.raises(ValueError):
        gold_stock_daily_trend_channel_path(Path(DEFAULT_LAKE_ROOT), partition_key)


@pytest.mark.parametrize(
    "forbidden_root",
    [DEFAULT_LAKE_ROOT, "/Volumes/datasource/goldenshare-tushare-lake"],
)
def test_staging_path_rejects_formal_and_legacy_lake_roots(
    forbidden_root: str,
) -> None:
    with pytest.raises(ValueError, match="must not use a formal or legacy Lake root"):
        gold_stock_daily_trend_channel_staging_path(
            Path(forbidden_root),
            "run-123",
            "2026-08-31",
        )


def test_catalog_partition_and_performance_contracts_are_aligned() -> None:
    result_entry = get_lake_asset_catalog_entry("gold_stock_daily_trend_channel")
    state_entry = get_lake_asset_catalog_entry(
        "gold_stock_daily_trend_channel_state"
    )

    assert result_entry.dataset_id == "stock_daily_trend_channel"
    assert result_entry.data_contract == "gold_stock_daily_qfq_trend_channel"
    assert result_entry.column_schema == GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA
    assert result_entry.blocking_check_names == (
        "gold_stock_daily_trend_channel_contract_check",
        "gold_stock_daily_trend_channel_input_coverage_check",
    )
    assert state_entry.dataset_id == "stock_daily_trend_channel_state"
    assert state_entry.data_contract == "gold_stock_daily_qfq_trend_channel_state"
    assert state_entry.column_schema == GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA
    assert state_entry.blocking_check_names == (
        "gold_stock_daily_trend_channel_state_contract_check",
    )

    for entry in (result_entry, state_entry):
        assert entry.write_policy is WritePolicy.PARTITION_FILE_ATOMIC_REPLACE
        assert entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
        assert entry.ingestion_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
        assert entry.bootstrap_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
        assert entry.performance_contract.batch_grain == "trade_date"
        assert entry.performance_contract.compute_engine is ComputeEngine.DUCKDB_SQL
        assert entry.performance_contract.python_row_loop_allowed is False
        assert (
            entry.performance_contract.source_request_policy
            == "read_upstream_assets_only"
        )
        partition_model = get_partition_model_definition(entry.partition_model)
        assert partition_model.family is PartitionModelFamily.TRADE_DATE_PARTITION
        assert partition_model.physical_layout is PartitionPhysicalLayout.PARTITION_FILE
        assert partition_model.dagster_partition_dimension == "trade_date"
        assert partition_model.asset_family == "stock_daily_trend_channel"

    assert result_entry.partition_model is (
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_TREND_CHANNEL
    )
    assert state_entry.partition_model is (
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_TREND_CHANNEL_STATE
    )


def test_trend_channel_uses_an_independent_dynamic_partition_definition() -> None:
    assert cn_a_stock_daily_trend_channel_trade_days.name == (
        "cn_a_stock_daily_trend_channel_trade_days"
    )
    assert cn_a_stock_daily_trend_channel_trade_days is not cn_a_stock_trade_days


def test_formula_kernel_has_no_dagster_runtime_or_python_detail_loop() -> None:
    formula_path = (
        Path(__file__).resolve().parents[1]
        / "src/orchestrator/defs/stock_daily_trend_channel.py"
    )
    source = formula_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "dagster" not in imported_modules
    assert "duckdb" not in imported_modules
    formula_function_names = {
        "build_stock_daily_trend_channel_daily_sql",
        "build_stock_daily_trend_channel_history_segment_sql",
        "build_stock_daily_trend_channel_repair_segment_sql",
        "_build_stock_daily_trend_channel_sql",
    }
    formula_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in formula_function_names
    }
    assert formula_functions.keys() == formula_function_names
    assert not any(
        isinstance(node, (ast.For, ast.AsyncFor))
        for function in formula_functions.values()
        for node in ast.walk(function)
    )
    assert "duckdb.connect" not in source
