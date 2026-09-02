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
    list_lake_asset_keys,
)
from orchestrator.defs.catalog.lake_assets import AssetLayer
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.run_contracts.etf_daily import (
    RAW_FUND_ADJ_CHECKS,
    RAW_FUND_DAILY_CHECKS,
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    SILVER_ETF_DAILY_BLOCKING_CHECKS,
)


def test_etf_daily_partition_models_are_registered() -> None:
    expected = {
        PartitionModel.TRADE_DATE_PARTITION_RAW_FUND_DAILY: (
            AssetLayer.RAW,
            "fund_daily",
        ),
        PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_DAILY: (
            AssetLayer.SILVER,
            "etf_daily",
        ),
        PartitionModel.TRADE_DATE_PARTITION_RAW_FUND_ADJ: (
            AssetLayer.RAW,
            "fund_adj",
        ),
        PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_ADJ_FACTOR: (
            AssetLayer.SILVER,
            "etf_adj_factor",
        ),
    }

    for model, (layer, asset_family) in expected.items():
        definition = get_partition_model_definition(model)
        assert definition.family is PartitionModelFamily.TRADE_DATE_PARTITION
        assert definition.layer is layer
        assert definition.asset_family == asset_family
        assert definition.dagster_partition_dimension == "trade_date"
        assert definition.physical_layout is PartitionPhysicalLayout.PARTITION_FILE
        assert "ETF 行情共享交易日分区" in definition.notes


def test_p3_activates_all_four_catalog_assets() -> None:
    asset_keys = set(list_lake_asset_keys())
    assert {
        "raw_tushare_fund_daily",
        "raw_tushare_fund_adj",
        "silver_etf_daily",
        "silver_etf_adj_factor",
    } <= asset_keys


def test_raw_catalog_entries_match_the_p2_source_and_performance_contract() -> None:
    for asset_key, dataset_id, source_api, checks, request_policy in (
        (
            "raw_tushare_fund_daily",
            "fund_daily",
            "fund_daily",
            RAW_FUND_DAILY_CHECKS,
            "trade_date_limit_5000_max_requests_2_max_elapsed_30s",
        ),
        (
            "raw_tushare_fund_adj",
            "fund_adj",
            "fund_adj",
            RAW_FUND_ADJ_CHECKS,
            "trade_date_limit_2000_max_requests_4_max_elapsed_30s",
        ),
    ):
        entry = get_lake_asset_catalog_entry(asset_key)
        assert entry.dataset_id == dataset_id
        assert entry.layer is AssetLayer.RAW
        assert entry.data_contract_source is DataContractSource.TUSHARE_RAW_CONTRACT
        assert entry.source_api == source_api
        assert entry.ingestion_sources == (IngestionSource.TUSHARE_API,)
        assert entry.default_daily_ingestion_source is IngestionSource.TUSHARE_API
        assert entry.bootstrap_sources == (IngestionSource.TUSHARE_API,)
        assert entry.blocking_check_names == checks
        assert entry.write_policy is WritePolicy.PARTITION_FILE_ATOMIC_REPLACE
        assert entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
        assert entry.performance_contract.batch_grain == "trade_date"
        assert (
            entry.performance_contract.compute_engine
            is ComputeEngine.TUSHARE_RESOURCE
        )
        assert entry.performance_contract.python_row_loop_allowed is False
        assert entry.performance_contract.source_request_policy == request_policy


def test_etf_daily_reuses_the_existing_etf_partition_definition() -> None:
    assert cn_a_etf_mins_trade_days.name == "cn_a_etf_mins_trade_days"


def test_silver_catalog_entries_match_the_p3_filter_and_performance_contract() -> None:
    for asset_key, dataset_id, checks, partition_model in (
        (
            "silver_etf_daily",
            "etf_daily",
            SILVER_ETF_DAILY_BLOCKING_CHECKS,
            PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_DAILY,
        ),
        (
            "silver_etf_adj_factor",
            "etf_adj_factor",
            SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
            PartitionModel.TRADE_DATE_PARTITION_SILVER_ETF_ADJ_FACTOR,
        ),
    ):
        entry = get_lake_asset_catalog_entry(asset_key)
        assert entry.dataset_id == dataset_id
        assert entry.layer is AssetLayer.SILVER
        assert entry.data_contract_source is DataContractSource.DERIVED_CONTRACT
        assert entry.source_api is None
        assert entry.ingestion_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
        assert (
            entry.default_daily_ingestion_source
            is IngestionSource.DERIVED_FROM_ASSETS
        )
        assert entry.bootstrap_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
        assert entry.blocking_check_names == checks
        assert entry.partition_model is partition_model
        assert entry.write_policy is WritePolicy.PARTITION_FILE_ATOMIC_REPLACE
        assert entry.event_policy is EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL
        assert entry.performance_contract.batch_grain == "trade_date"
        assert entry.performance_contract.compute_engine is ComputeEngine.DUCKDB_SQL
        assert entry.performance_contract.python_row_loop_allowed is False
        assert (
            entry.performance_contract.source_request_policy
            == "read_upstream_assets_only"
        )
