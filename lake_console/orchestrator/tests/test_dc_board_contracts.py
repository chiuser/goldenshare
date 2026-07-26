from pathlib import Path

from orchestrator.defs.catalog.lake_assets import (
    IngestionSource,
    EventPolicy,
    PartitionPhysicalLayout,
    PartitionModel,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
    SILVER_DC_INDEX_SCHEMA,
    SILVER_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_ELAPSED_MS,
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
    DC_DAILY_HISTORY_START_DATE,
    DC_DAILY_FIELDS,
    DC_DAILY_REQUEST_POLICY_NAME,
    DC_INDEX_HISTORY_START_DATE,
    DC_INDEX_FIELDS,
    DC_INDEX_REQUEST_POLICY_NAME,
    DC_MEMBER_DAILY_SOURCE_METHOD,
    DC_MEMBER_FIELDS,
    DC_MEMBER_BOOTSTRAP_SOURCE_METHOD,
    DC_MEMBER_HISTORY_START_DATE,
    DC_MEMBER_REQUEST_POLICY_NAME,
)


def _column_names(schema: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(column.name for column in schema)


def test_dc_board_contracts_keep_source_fields_and_category_key() -> None:
    assert DC_INDEX_HISTORY_START_DATE == "2024-12-20"
    assert DC_MEMBER_HISTORY_START_DATE == "2024-12-20"
    assert DC_DAILY_HISTORY_START_DATE == "2024-01-02"
    assert _column_names(RAW_TUSHARE_DC_INDEX_SCHEMA) == DC_INDEX_FIELDS
    assert _column_names(RAW_TUSHARE_DC_MEMBER_SCHEMA) == DC_MEMBER_FIELDS
    assert _column_names(RAW_TUSHARE_DC_DAILY_SCHEMA) == DC_DAILY_FIELDS

    assert _column_names(SILVER_DC_INDEX_SCHEMA) == DC_INDEX_FIELDS
    assert _column_names(SILVER_DC_MEMBER_SCHEMA) == DC_MEMBER_FIELDS
    assert _column_names(SILVER_DC_DAILY_SCHEMA) == DC_DAILY_FIELDS
    assert "category" in DC_DAILY_FIELDS

    raw_daily_types = {
        column.name: column.type for column in RAW_TUSHARE_DC_DAILY_SCHEMA
    }
    silver_daily_types = {
        column.name: column.type for column in SILVER_DC_DAILY_SCHEMA
    }
    assert raw_daily_types["trade_date"] == "VARCHAR"
    assert silver_daily_types["trade_date"] == "DATE"
    assert raw_daily_types["category"] == "VARCHAR"
    assert silver_daily_types["category"] == "VARCHAR"


def test_dc_board_paths_are_trade_date_partition_files() -> None:
    root = Path("/tmp/test-lake")
    date = "2026-07-14"
    expected = {
        raw_dc_index_path(root, date): "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet",
        raw_dc_member_path(root, date): "raw/board/dc_member/trade_date=2026-07-14/part-000.parquet",
        raw_dc_daily_path(root, date): "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet",
        silver_dc_index_path(root, date): "silver/board/dc_index/trade_date=2026-07-14/part-000.parquet",
        silver_dc_member_path(root, date): "silver/board/dc_member/trade_date=2026-07-14/part-000.parquet",
        silver_dc_daily_path(root, date): "silver/board/dc_daily/trade_date=2026-07-14/part-000.parquet",
    }
    for path, suffix in expected.items():
        assert path.as_posix() == f"/tmp/test-lake/{suffix}"


def test_dc_board_catalog_has_six_explicit_entries() -> None:
    entries = {
        asset_key: get_lake_asset_catalog_entry(asset_key)
        for asset_key in (
            "raw_tushare_dc_index",
            "raw_tushare_dc_member",
            "raw_tushare_dc_daily",
            "silver_dc_index",
            "silver_dc_member",
            "silver_dc_daily",
        )
    }

    assert entries["raw_tushare_dc_index"].bootstrap_sources == (
        IngestionSource.TUSHARE_API,
    )
    assert (
        entries["raw_tushare_dc_index"].performance_contract.source_request_policy
        == DC_INDEX_REQUEST_POLICY_NAME
    )
    assert entries["raw_tushare_dc_daily"].bootstrap_sources == (
        IngestionSource.TUSHARE_API,
    )
    assert (
        entries["raw_tushare_dc_daily"].performance_contract.source_request_policy
        == DC_DAILY_REQUEST_POLICY_NAME
    )

    member = entries["raw_tushare_dc_member"]
    assert member.ingestion_sources == (
        IngestionSource.TUSHARE_API,
        IngestionSource.PROD_DB_READONLY,
    )
    assert member.default_daily_ingestion_source is IngestionSource.TUSHARE_API
    assert member.bootstrap_sources == (IngestionSource.PROD_DB_READONLY,)
    assert member.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
    assert member.performance_contract.source_request_policy == (
        DC_MEMBER_REQUEST_POLICY_NAME
    )
    assert DC_MEMBER_BOOTSTRAP_SOURCE_METHOD == "prod_db_readonly_export"
    assert DC_MEMBER_DAILY_SOURCE_METHOD == "tushare_api_by_ts_code"

    for asset_key, expected_model in {
        "raw_tushare_dc_index": PartitionModel.TRADE_DATE_PARTITION_RAW_DC_INDEX,
        "raw_tushare_dc_member": PartitionModel.TRADE_DATE_PARTITION_RAW_DC_MEMBER,
        "raw_tushare_dc_daily": PartitionModel.TRADE_DATE_PARTITION_RAW_DC_DAILY,
        "silver_dc_index": PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_INDEX,
        "silver_dc_member": PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_MEMBER,
        "silver_dc_daily": PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_DAILY,
    }.items():
        entry = entries[asset_key]
        model = get_partition_model_definition(entry.partition_model)
        assert entry.partition_model is expected_model
        assert model.physical_layout is PartitionPhysicalLayout.PARTITION_FILE
        assert model.dagster_partition_dimension == "trade_date"
        assert entry.blocking_check_names
        assert entry.path_template is not None

    for asset_key in (
        "silver_dc_index",
        "silver_dc_member",
        "silver_dc_daily",
    ):
        assert entries[asset_key].bootstrap_sources == (
            IngestionSource.DERIVED_FROM_ASSETS,
        )

    assert DC_BOARD_MAX_REQUESTS_PER_PARTITION == 1_200
    assert DC_BOARD_MAX_ELAPSED_MS == 600_000
