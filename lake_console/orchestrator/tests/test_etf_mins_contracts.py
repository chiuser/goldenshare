from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.defs.catalog import (
    ComputeEngine,
    DataContractSource,
    EventPolicy,
    IngestionSource,
    PartitionModel,
    PartitionModelFamily,
    PartitionPhysicalLayout,
    WritePolicy,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
    list_lake_asset_entries_by_dataset_id,
)
from orchestrator.defs.partitions import (
    cn_a_etf_mins_trade_days,
    cn_a_index_mins_trade_days,
    cn_a_stock_mins_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    PATH_TEMPLATE_SNAPSHOT_ID,
    etf_basic_staging_path,
    etf_mins_staging_path,
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
    silver_etf_mins_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_ETF_MINS_SCHEMA,
    SILVER_ETF_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_ASSET_FREQS,
    ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT,
    ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES,
    ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT,
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX,
    ETF_MINS_SOURCE_FREQS,
    asset_freq_for_etf_mins_source_freq,
    expected_etf_mins_source_exchange,
    normalize_etf_mins_asset_freq,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
    source_freq_for_etf_mins_asset_freq,
)
from orchestrator.defs.run_contracts.metadata import SourceSystem


def test_frequency_date_and_exchange_contracts_are_centralized() -> None:
    assert ETF_MINS_SOURCE_FREQS == ("1min", "5min", "15min", "30min", "60min")
    assert ETF_MINS_ASSET_FREQS == (1, 5, 15, 30, 60)
    for asset_freq, source_freq in zip(
        ETF_MINS_ASSET_FREQS,
        ETF_MINS_SOURCE_FREQS,
        strict=True,
    ):
        assert source_freq_for_etf_mins_asset_freq(asset_freq) == source_freq
        assert asset_freq_for_etf_mins_source_freq(source_freq) == asset_freq

    assert normalize_etf_mins_trade_date("2026-08-28") == "2026-08-28"
    assert ETF_MINS_SOURCE_EXCHANGE_BY_CODE_SUFFIX == {
        "SH": "XSHG",
        "SZ": "XSHE",
    }
    assert expected_etf_mins_source_exchange("510300.SH") == "XSHG"
    assert expected_etf_mins_source_exchange("159915.sz") == "XSHE"

    with pytest.raises(ValueError):
        normalize_etf_mins_source_freq("1m")
    with pytest.raises(ValueError):
        normalize_etf_mins_asset_freq(True)
    with pytest.raises(ValueError):
        normalize_etf_mins_trade_date("20260828")
    with pytest.raises(ValueError):
        expected_etf_mins_source_exchange("920001.BJ")


def test_operational_constants_match_the_approved_lld() -> None:
    assert ETF_MINS_SENSOR_WINDOW_LIMIT == 10
    assert ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT == 20
    assert ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES == 10_000
    assert ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER == 1.25
    assert ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT == 20
    assert ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat() == "2026-01-01"


def test_minute_schema_is_an_exact_eleven_column_copy_contract() -> None:
    raw_columns = tuple(column.name for column in RAW_ETF_MINS_SCHEMA)
    silver_columns = tuple(column.name for column in SILVER_ETF_MINS_SCHEMA)
    raw_types = tuple(column.type for column in RAW_ETF_MINS_SCHEMA)
    silver_types = tuple(column.type for column in SILVER_ETF_MINS_SCHEMA)

    assert raw_columns == ETF_MINS_SOURCE_COLUMNS
    assert silver_columns == ETF_MINS_SOURCE_COLUMNS
    assert raw_types == silver_types
    assert raw_types == (
        "VARCHAR",
        "VARCHAR",
        "TIMESTAMP",
        "DOUBLE",
        "DOUBLE",
        "DOUBLE",
        "DOUBLE",
        "BIGINT",
        "DOUBLE",
        "DOUBLE",
        "VARCHAR",
    )
    assert "trade_date" not in raw_columns


def test_paths_match_formal_lake_and_operation_staging_contracts() -> None:
    root = Path("data_lake")
    staging_root = Path("data_lake_staging")
    snapshot_id = "a" * 64

    assert raw_etf_basic_snapshot_path(root, snapshot_id).as_posix() == (
        f"data_lake/raw/tushare/etf_basic/snapshot_id={snapshot_id}/part-000.parquet"
    )
    assert silver_etf_basic_snapshot_path(root, snapshot_id).as_posix() == (
        f"data_lake/silver/basic/etf_basic/snapshot_id={snapshot_id}/part-000.parquet"
    )
    assert raw_etf_mins_path(root, 5, "2026-08-28").as_posix() == (
        "data_lake/raw/tushare/etf_mins/freq=5min/"
        "trade_date=2026-08-28/part-000.parquet"
    )
    assert silver_etf_mins_path(root, "5min", "2026-08-28").as_posix() == (
        "data_lake/silver/quote/etf_mins/freq=5min/"
        "trade_date=2026-08-28/part-000.parquet"
    )
    assert etf_basic_staging_path(staging_root, "run-1", "raw").as_posix() == (
        "data_lake_staging/etf_basic/run_id=run-1/raw/part-000.parquet"
    )
    assert etf_mins_staging_path(
        staging_root,
        "operation-1",
        "silver",
        60,
        "2026-08-28",
    ).as_posix() == (
        "data_lake_staging/etf_mins/operation_id=operation-1/silver/"
        "freq=60min/trade_date=2026-08-28/part-000.parquet"
    )

    assert raw_etf_basic_snapshot_path(
        PATH_TEMPLATE_LAKE_ROOT,
        PATH_TEMPLATE_SNAPSHOT_ID,
    ).as_posix().endswith("snapshot_id={snapshot_id}/part-000.parquet")
    assert raw_etf_mins_path(
        PATH_TEMPLATE_LAKE_ROOT,
        1,
        PATH_TEMPLATE_PARTITION_KEY,
    ).as_posix().endswith("freq=1min/trade_date={partition_key}/part-000.parquet")


@pytest.mark.parametrize(
    ("builder", "args"),
    (
        (raw_etf_basic_snapshot_path, (Path("lake"), "A" * 64)),
        (raw_etf_basic_snapshot_path, (Path("lake"), "../bad")),
        (raw_etf_mins_path, (Path("lake"), "2min", "2026-08-28")),
        (raw_etf_mins_path, (Path("lake"), "1min", "20260828")),
        (etf_basic_staging_path, (Path("staging"), "../bad", "raw")),
        (etf_basic_staging_path, (Path("staging"), "run-1", "gold")),
        (
            etf_mins_staging_path,
            (Path("staging"), "operation/1", "raw", 1, "2026-08-28"),
        ),
    ),
)
def test_paths_reject_unregistered_or_unsafe_components(builder, args) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        builder(*args)


def test_etf_minutes_use_a_dedicated_dynamic_partition_definition() -> None:
    assert cn_a_etf_mins_trade_days.name == "cn_a_etf_mins_trade_days"
    assert cn_a_etf_mins_trade_days is not cn_a_index_mins_trade_days
    assert cn_a_etf_mins_trade_days is not cn_a_stock_mins_trade_days


def test_catalog_registers_twelve_contract_only_etf_entries() -> None:
    basic_entries = list_lake_asset_entries_by_dataset_id("etf_basic")
    minute_entries = list_lake_asset_entries_by_dataset_id("etf_mins")
    assert len(basic_entries) == 2
    assert len(minute_entries) == 10

    raw_basic = get_lake_asset_catalog_entry("raw_tushare_etf_basic")
    silver_basic = get_lake_asset_catalog_entry("silver_etf_basic")
    assert raw_basic.source_system is SourceSystem.TUSHARE
    assert raw_basic.data_contract_source is DataContractSource.TUSHARE_RAW_CONTRACT
    assert raw_basic.ingestion_sources == (IngestionSource.TUSHARE_API,)
    assert raw_basic.default_daily_ingestion_source is IngestionSource.TUSHARE_API
    assert raw_basic.bootstrap_sources == ()
    assert raw_basic.write_policy is WritePolicy.SINGLE_FILE_ATOMIC_REPLACE
    assert raw_basic.event_policy is EventPolicy.DAGSTER_RUN_ONLY
    assert raw_basic.partition_model is PartitionModel.FULL_FILE_RAW_ETF_BASIC_VERSIONED
    assert raw_basic.source_api == "etf_basic"
    assert raw_basic.source_doc == "docs/sources/tushare/ETF专题/0385_ETF基础信息.md"
    assert silver_basic.source_system is SourceSystem.DERIVED
    assert silver_basic.bootstrap_sources == ()
    assert silver_basic.partition_model is (
        PartitionModel.FULL_FILE_SILVER_ETF_BASIC_VERSIONED
    )

    for freq in ETF_MINS_ASSET_FREQS:
        raw_entry = get_lake_asset_catalog_entry(f"raw_etf_mins_{freq}m")
        silver_entry = get_lake_asset_catalog_entry(f"silver_etf_mins_{freq}m")
        assert raw_entry.source_system is SourceSystem.TUSHARE
        assert raw_entry.data_contract_source is DataContractSource.TUSHARE_RAW_CONTRACT
        assert raw_entry.ingestion_sources == (IngestionSource.PROD_DB_READONLY,)
        assert raw_entry.default_daily_ingestion_source is (
            IngestionSource.PROD_DB_READONLY
        )
        assert raw_entry.bootstrap_sources == (IngestionSource.PROD_DB_READONLY,)
        assert raw_entry.blocking_check_names == raw_etf_mins_check_names(freq)
        assert raw_entry.performance_contract.compute_engine is ComputeEngine.DUCKDB_SQL
        assert "prod-raw-db.raw_tushare.etf_minute_bar" in raw_entry.notes
        assert silver_entry.source_system is SourceSystem.DERIVED
        assert silver_entry.bootstrap_sources == (
            IngestionSource.DERIVED_FROM_ASSETS,
        )
        assert silver_entry.blocking_check_names == silver_etf_mins_check_names(freq)
        assert raw_entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
        assert silver_entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL


def test_partition_models_match_their_physical_layouts() -> None:
    expected = {
        PartitionModel.FULL_FILE_RAW_ETF_BASIC_VERSIONED: (
            PartitionModelFamily.FULL_FILE,
            PartitionPhysicalLayout.SINGLE_FILE,
        ),
        PartitionModel.FULL_FILE_SILVER_ETF_BASIC_VERSIONED: (
            PartitionModelFamily.FULL_FILE,
            PartitionPhysicalLayout.SINGLE_FILE,
        ),
        PartitionModel.TRADE_DATE_PARTITION_RAW_ETF_MINS: (
            PartitionModelFamily.TRADE_DATE_PARTITION,
            PartitionPhysicalLayout.PARTITION_FILE,
        ),
        PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_MINS: (
            PartitionModelFamily.TRADE_DATE_PARTITION,
            PartitionPhysicalLayout.PARTITION_FILE,
        ),
    }
    for model, (family, layout) in expected.items():
        definition = get_partition_model_definition(model)
        assert definition.family is family
        assert definition.physical_layout is layout
