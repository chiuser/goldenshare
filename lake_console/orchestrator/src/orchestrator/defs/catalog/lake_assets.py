"""Read-only catalog registry for active Dagster lake assets."""

from dataclasses import dataclass
from enum import Enum

from orchestrator.defs.catalog.name_mapping import get_dataset_chinese_name
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    PATH_TEMPLATE_TS_CODE,
    PATH_TEMPLATE_YEAR,
    gold_market_breadth_daily_path,
    gold_market_major_indices_daily_path,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
    gold_stock_daily_qfq_path,
    gold_stock_return_distribution_path,
    gold_wealth_market_turnover_path,
    lake_path_template,
    raw_adj_factor_path,
    raw_index_basic_path,
    raw_index_daily_path,
    raw_namechange_path,
    raw_stock_basic_path,
    raw_stock_daily_path,
    raw_stk_nineturn_path,
    raw_stk_mins_path,
    raw_suspend_d_path,
    raw_trade_calendar_path,
    silver_adj_factor_path,
    silver_index_basic_path,
    silver_index_daily_path,
    silver_namechange_path,
    silver_stk_mins_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_nineturn_daily_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
    GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
    RAW_STK_MINS_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    RAW_TUSHARE_NAMECHANGE_SCHEMA,
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_NAMECHANGE_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_NINETURN_DAILY_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import AssetLayer, DataDomain
from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.metadata import SourceSystem


class DataContractSource(str, Enum):
    TUSHARE_RAW_CONTRACT = "tushare_raw_contract"
    PROD_SERVING_CONTRACT = "prod_serving_contract"
    DERIVED_CONTRACT = "derived_contract"
    SEED_CONTRACT = "seed_contract"
    PLATFORM_CONTRACT = "platform_contract"


class IngestionSource(str, Enum):
    TUSHARE_API = "tushare_api"
    PROD_DB_READONLY = "prod_db_readonly"
    OLD_LAKE_BOOTSTRAP = "old_lake_bootstrap"
    DERIVED_FROM_ASSETS = "derived_from_assets"
    SEED_FILE = "seed_file"
    INFRASTRUCTURE_CHECK = "infrastructure_check"
    CLICKHOUSE_SYNC = "clickhouse_sync"


class PartitionModelFamily(str, Enum):
    FULL_FILE = "full_file"
    TRADE_DATE_PARTITION = "trade_date_partition"
    SERVING_TABLE = "serving_table"
    NON_PARTITIONED = "non_partitioned"


class PartitionPhysicalLayout(str, Enum):
    SINGLE_FILE = "single_file"
    PARTITION_FILE = "partition_file"
    STOCK_YEAR_FILE = "stock_year_file"
    SERVING_TABLE = "serving_table"
    POSTGRES_TABLE = "postgres_table"
    NO_DATA_FILE = "no_data_file"


class PartitionModel(str, Enum):
    FULL_FILE_RAW_TRADE_CALENDAR = "full_file_raw_trade_calendar"
    FULL_FILE_SILVER_TRADE_CALENDAR = "full_file_silver_trade_calendar"
    FULL_FILE_RAW_STOCK_BASIC = "full_file_raw_stock_basic"
    FULL_FILE_SILVER_STOCK_BASIC = "full_file_silver_stock_basic"
    FULL_FILE_SILVER_STOCK_LIFECYCLE = "full_file_silver_stock_lifecycle"
    FULL_FILE_RAW_NAMECHANGE = "full_file_raw_namechange"
    FULL_FILE_SILVER_NAMECHANGE = "full_file_silver_namechange"
    FULL_FILE_SILVER_STOCK_IDENTITY_MAP = "full_file_silver_stock_identity_map"
    FULL_FILE_RAW_INDEX_BASIC = "full_file_raw_index_basic"
    FULL_FILE_SILVER_INDEX_BASIC = "full_file_silver_index_basic"

    TRADE_DATE_PARTITION_RAW_STOCK_DAILY = "trade_date_partition_raw_stock_daily"
    TRADE_DATE_PARTITION_SILVER_STOCK_DAILY = (
        "trade_date_partition_silver_stock_daily"
    )
    TRADE_DATE_PARTITION_RAW_STK_NINETURN = (
        "trade_date_partition_raw_stk_nineturn"
    )
    TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY = (
        "trade_date_partition_silver_stock_nineturn_daily"
    )
    TRADE_DATE_PARTITION_RAW_ADJ_FACTOR = "trade_date_partition_raw_adj_factor"
    TRADE_DATE_PARTITION_SILVER_ADJ_FACTOR = "trade_date_partition_silver_adj_factor"
    TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ = (
        "trade_date_partition_gold_stock_daily_qfq"
    )
    TRADE_DATE_PARTITION_RAW_SUSPEND_D = "trade_date_partition_raw_suspend_d"
    TRADE_DATE_PARTITION_SILVER_STOCK_SUSPEND_DAILY = (
        "trade_date_partition_silver_stock_suspend_daily"
    )
    TRADE_DATE_PARTITION_RAW_INDEX_DAILY = "trade_date_partition_raw_index_daily"
    TRADE_DATE_PARTITION_SILVER_INDEX_DAILY = (
        "trade_date_partition_silver_index_daily"
    )
    TRADE_DATE_PARTITION_RAW_STOCK_MINS = "trade_date_partition_raw_stock_mins"
    TRADE_DATE_PARTITION_SILVER_STOCK_MINS = "trade_date_partition_silver_stock_mins"
    TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_STOCK_YEAR_FILE = (
        "trade_date_partition_gold_stock_mins_qfq_stock_year_file"
    )
    TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STOCK_YEAR_FILE = (
        "trade_date_partition_gold_stock_mins_qfq_macd_kdj_stock_year_file"
    )
    TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STATE = (
        "trade_date_partition_gold_stock_mins_qfq_macd_kdj_state"
    )
    TRADE_DATE_PARTITION_GOLD_MARKET_MAJOR_INDICES_DAILY = (
        "trade_date_partition_gold_market_major_indices_daily"
    )
    TRADE_DATE_PARTITION_GOLD_MARKET_BREADTH = (
        "trade_date_partition_gold_market_breadth"
    )
    TRADE_DATE_PARTITION_GOLD_STOCK_RETURN_DISTRIBUTION = (
        "trade_date_partition_gold_stock_return_distribution"
    )
    TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER = (
        "trade_date_partition_gold_wealth_market_turnover"
    )
    SERVING_TABLE_PROD_WEALTH_MARKET_TURNOVER = (
        "serving_table_prod_wealth_market_turnover"
    )

    SERVING_TABLE_SERVING_MARKET_BREADTH = "serving_table_serving_market_breadth"
    NON_PARTITIONED_PLATFORM_LAKE_ROOT_HEALTH = (
        "non_partitioned_platform_lake_root_health"
    )


@dataclass(frozen=True, slots=True)
class PartitionModelDefinition:
    model: PartitionModel
    family: PartitionModelFamily
    layer: AssetLayer
    asset_family: str
    dagster_partition_dimension: str | None
    physical_layout: PartitionPhysicalLayout
    notes: str = ""


class WritePolicy(str, Enum):
    SINGLE_FILE_ATOMIC_REPLACE = "single_file_atomic_replace"
    PARTITION_FILE_ATOMIC_REPLACE = "partition_file_atomic_replace"
    STOCK_YEAR_ATOMIC_REPLACE = "stock_year_atomic_replace"
    NO_DATA_FILE = "no_data_file"
    CLICKHOUSE_TABLE_SYNC = "clickhouse_table_sync"
    POSTGRES_TABLE_SYNC = "postgres_table_sync"


class EventPolicy(str, Enum):
    DAGSTER_RUN_ONLY = "dagster_run_only"
    SUPPORTS_RUNLESS_EVENT_BACKFILL = "supports_runless_event_backfill"
    HEALTH_MATERIALIZATION_ONLY = "health_materialization_only"


class ComputeEngine(str, Enum):
    DUCKDB_SQL = "duckdb_sql"
    TUSHARE_RESOURCE = "tushare_resource"
    FILESYSTEM_CHECK = "filesystem_check"
    CLICKHOUSE_CLIENT = "clickhouse_client"
    POSTGRES_SQL = "postgres_sql"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class LakeAssetPerformanceContract:
    batch_grain: str
    compute_engine: ComputeEngine
    python_row_loop_allowed: bool
    source_request_policy: str
    notes: str


@dataclass(frozen=True, slots=True)
class LakeAssetCatalogEntry:
    asset_key: str
    dataset_id: str
    dataset_name: str
    layer: AssetLayer
    data_domain: DataDomain
    group_name: str
    source_system: SourceSystem
    data_contract: str
    data_contract_source: DataContractSource
    column_schema: tuple[ColumnContract, ...] | None
    path_template: str | None
    partition_model: PartitionModel
    source_api: str | None
    source_doc: str | None
    ingestion_sources: tuple[IngestionSource, ...]
    default_daily_ingestion_source: IngestionSource | None
    bootstrap_sources: tuple[IngestionSource, ...]
    blocking_check_names: tuple[str, ...]
    write_policy: WritePolicy
    event_policy: EventPolicy
    performance_contract: LakeAssetPerformanceContract
    notes: str = ""


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
RAW_SUSPEND_D_CHECKS = (
    "raw_suspend_d_contract_check",
    "raw_suspend_d_partition_allowed_check",
)
SILVER_STOCK_SUSPEND_DAILY_CHECKS = (
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
GOLD_STOCK_DAILY_QFQ_CHECKS = (
    "gold_stock_daily_qfq_contract_check",
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
GOLD_STK_MINS_QFQ_BASE_CHECKS = (
    "gold_stk_mins_qfq_contract_check",
    "gold_stk_mins_qfq_key_integrity_check",
    "gold_stk_mins_qfq_value_domain_check",
)
GOLD_STK_MINS_QFQ_NATIVE_CHECKS = (
    *GOLD_STK_MINS_QFQ_BASE_CHECKS,
    "gold_stk_mins_qfq_formula_matches_silver_adj_factor",
    "gold_stk_mins_qfq_source_coverage_check",
)
GOLD_STK_MINS_QFQ_DERIVED_CHECKS = (
    "gold_stk_mins_qfq_derived_formula_matches_source",
    "gold_stk_mins_qfq_derived_source_coverage_check",
    *GOLD_STK_MINS_QFQ_BASE_CHECKS,
)
GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_contract_check",
    "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
    "gold_stk_mins_qfq_macd_kdj_formula_sample_check",
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS = (
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
RAW_INDEX_DAILY_BY_DATE_CHECKS = (
    "raw_index_daily_code_coverage_check",
    "raw_index_daily_file_contract_check",
)
SILVER_INDEX_DAILY_CHECKS = (
    "silver_index_daily_contract_check",
    "silver_index_daily_key_integrity_check",
    "silver_index_daily_value_domain_check",
    "silver_index_daily_registered_code_coverage_check",
)
GOLD_MARKET_MAJOR_INDICES_DAILY_CHECKS = (
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
GOLD_WEALTH_MARKET_TURNOVER_CHECKS = (
    "gold_wealth_market_turnover_integrity_check",
)
CH_SHARE_FACT_MARKET_BREADTH_DAILY_CHECKS = (
    "ch_share_fact_market_breadth_contract_check",
    "ch_share_fact_market_breadth_gold_reconciliation_check",
)
PROD_CH_SHARE_FACT_MARKET_BREADTH_DAILY_CHECKS = (
    "prod_ch_share_fact_market_breadth_date_matches_partition",
    "prod_ch_share_fact_market_breadth_row_count_is_one",
    "prod_ch_share_fact_market_breadth_row_matches_local",
    "prod_ch_share_fact_market_breadth_updated_at_not_older_than_local",
)
LAKE_ROOT_HEALTH_CHECKS = (
    "lake_root_health_ready",
)


def _perf(
    *,
    batch_grain: str,
    compute_engine: ComputeEngine,
    source_request_policy: str,
    python_row_loop_allowed: bool = False,
    notes: str = "",
) -> LakeAssetPerformanceContract:
    return LakeAssetPerformanceContract(
        batch_grain=batch_grain,
        compute_engine=compute_engine,
        python_row_loop_allowed=python_row_loop_allowed,
        source_request_policy=source_request_policy,
        notes=notes,
    )


def _model(
    model: PartitionModel,
    family: PartitionModelFamily,
    layer: AssetLayer,
    asset_family: str,
    dagster_partition_dimension: str | None,
    physical_layout: PartitionPhysicalLayout,
    notes: str = "",
) -> PartitionModelDefinition:
    return PartitionModelDefinition(
        model=model,
        family=family,
        layer=layer,
        asset_family=asset_family,
        dagster_partition_dimension=dagster_partition_dimension,
        physical_layout=physical_layout,
        notes=notes,
    )


PARTITION_MODEL_DEFINITIONS = (
    _model(
        PartitionModel.FULL_FILE_RAW_TRADE_CALENDAR,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.RAW,
        "trade_calendar",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_TRADE_CALENDAR,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "trade_calendar",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_RAW_STOCK_BASIC,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.RAW,
        "stock_basic",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_STOCK_BASIC,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "stock_basic",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_STOCK_LIFECYCLE,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "stock_lifecycle",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_RAW_NAMECHANGE,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.RAW,
        "namechange",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_NAMECHANGE,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "namechange",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_STOCK_IDENTITY_MAP,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "stock_identity_map",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_RAW_INDEX_BASIC,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.RAW,
        "index_basic",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.FULL_FILE_SILVER_INDEX_BASIC,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "index_basic",
        None,
        PartitionPhysicalLayout.SINGLE_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_STOCK_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "stock_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "stock_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_STK_NINETURN,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "stk_nineturn",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "stock_nineturn_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_ADJ_FACTOR,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "adj_factor",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_ADJ_FACTOR,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "adj_factor",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_daily_qfq",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_SUSPEND_D,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "suspend_d",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_SUSPEND_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "stock_suspend_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "index_daily",
        "ts_code",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "index_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_STOCK_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "stock_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "stock_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_STOCK_YEAR_FILE,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_mins_qfq",
        "trade_date",
        PartitionPhysicalLayout.STOCK_YEAR_FILE,
        notes="Dagster partition is trade_date; physical files are freq/ts_code/year.",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STOCK_YEAR_FILE,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_mins_qfq_macd_kdj",
        "trade_date",
        PartitionPhysicalLayout.STOCK_YEAR_FILE,
        notes="Dagster partition is trade_date; physical files are freq/ts_code/year.",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STATE,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_mins_qfq_macd_kdj_state",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="State files are freq/trade_date partition files.",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_MARKET_MAJOR_INDICES_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "market_major_indices_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_MARKET_BREADTH,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "market_breadth",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_RETURN_DISTRIBUTION,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_return_distribution",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "wealth_market_turnover",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.SERVING_TABLE_PROD_WEALTH_MARKET_TURNOVER,
        PartitionModelFamily.SERVING_TABLE,
        AssetLayer.SERVING,
        "wealth_market_turnover",
        "trade_date",
        PartitionPhysicalLayout.POSTGRES_TABLE,
        notes="Prod PostgreSQL serving table sync partitioned by trade_date.",
    ),
    _model(
        PartitionModel.SERVING_TABLE_SERVING_MARKET_BREADTH,
        PartitionModelFamily.SERVING_TABLE,
        AssetLayer.SERVING,
        "market_breadth",
        "trade_date",
        PartitionPhysicalLayout.SERVING_TABLE,
    ),
    _model(
        PartitionModel.NON_PARTITIONED_PLATFORM_LAKE_ROOT_HEALTH,
        PartitionModelFamily.NON_PARTITIONED,
        AssetLayer.PLATFORM,
        "lake_root_health",
        None,
        PartitionPhysicalLayout.NO_DATA_FILE,
    ),
)


def _entry(
    *,
    asset_key: str,
    dataset_id: str,
    layer: AssetLayer,
    data_domain: DataDomain,
    group_name: str,
    source_system: SourceSystem,
    data_contract: str,
    data_contract_source: DataContractSource,
    column_schema: tuple[ColumnContract, ...] | None,
    path_template: str | None,
    partition_model: PartitionModel,
    source_api: str | None,
    source_doc: str | None,
    ingestion_sources: tuple[IngestionSource, ...],
    default_daily_ingestion_source: IngestionSource | None,
    bootstrap_sources: tuple[IngestionSource, ...],
    blocking_check_names: tuple[str, ...],
    write_policy: WritePolicy,
    event_policy: EventPolicy,
    performance_contract: LakeAssetPerformanceContract,
    notes: str = "",
) -> LakeAssetCatalogEntry:
    return LakeAssetCatalogEntry(
        asset_key=asset_key,
        dataset_id=dataset_id,
        dataset_name=get_dataset_chinese_name(dataset_id),
        layer=layer,
        data_domain=data_domain,
        group_name=group_name,
        source_system=source_system,
        data_contract=data_contract,
        data_contract_source=data_contract_source,
        column_schema=column_schema,
        path_template=path_template,
        partition_model=partition_model,
        source_api=source_api,
        source_doc=source_doc,
        ingestion_sources=ingestion_sources,
        default_daily_ingestion_source=default_daily_ingestion_source,
        bootstrap_sources=bootstrap_sources,
        blocking_check_names=blocking_check_names,
        write_policy=write_policy,
        event_policy=event_policy,
        performance_contract=performance_contract,
        notes=notes,
    )


def _tushare_raw_entry(
    *,
    asset_key: str,
    dataset_id: str,
    group_name: str,
    data_domain: DataDomain,
    data_contract: str,
    column_schema: tuple[ColumnContract, ...],
    path_template: str,
    partition_model: PartitionModel,
    source_api: str,
    source_doc: str,
    blocking_check_names: tuple[str, ...],
    batch_grain: str,
) -> LakeAssetCatalogEntry:
    return _entry(
        asset_key=asset_key,
        dataset_id=dataset_id,
        layer=AssetLayer.RAW,
        data_domain=data_domain,
        group_name=group_name,
        source_system=SourceSystem.TUSHARE,
        data_contract=data_contract,
        data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
        column_schema=column_schema,
        path_template=path_template,
        partition_model=partition_model,
        source_api=source_api,
        source_doc=source_doc,
        ingestion_sources=(IngestionSource.TUSHARE_API,),
        default_daily_ingestion_source=IngestionSource.TUSHARE_API,
        bootstrap_sources=(),
        blocking_check_names=blocking_check_names,
        write_policy=(
            WritePolicy.SINGLE_FILE_ATOMIC_REPLACE
            if batch_grain == "single_file"
            else WritePolicy.PARTITION_FILE_ATOMIC_REPLACE
        ),
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain=batch_grain,
            compute_engine=ComputeEngine.TUSHARE_RESOURCE,
            source_request_policy="tushare_request_per_asset_unit",
        ),
    )


def _derived_entry(
    *,
    asset_key: str,
    dataset_id: str,
    layer: AssetLayer,
    data_domain: DataDomain,
    group_name: str,
    data_contract: str,
    column_schema: tuple[ColumnContract, ...],
    path_template: str | None,
    partition_model: PartitionModel,
    blocking_check_names: tuple[str, ...],
    batch_grain: str,
    write_policy: WritePolicy,
    event_policy: EventPolicy = EventPolicy.DAGSTER_RUN_ONLY,
    compute_engine: ComputeEngine = ComputeEngine.DUCKDB_SQL,
    bootstrap_sources: tuple[IngestionSource, ...] = (),
    notes: str = "",
) -> LakeAssetCatalogEntry:
    return _entry(
        asset_key=asset_key,
        dataset_id=dataset_id,
        layer=layer,
        data_domain=data_domain,
        group_name=group_name,
        source_system=SourceSystem.DERIVED,
        data_contract=data_contract,
        data_contract_source=DataContractSource.DERIVED_CONTRACT,
        column_schema=column_schema,
        path_template=path_template,
        partition_model=partition_model,
        source_api=None,
        source_doc=None,
        ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        default_daily_ingestion_source=IngestionSource.DERIVED_FROM_ASSETS,
        bootstrap_sources=bootstrap_sources,
        blocking_check_names=blocking_check_names,
        write_policy=write_policy,
        event_policy=event_policy,
        performance_contract=_perf(
            batch_grain=batch_grain,
            compute_engine=compute_engine,
            source_request_policy="read_upstream_assets_only",
            notes=notes,
        ),
        notes=notes,
    )


LAKE_ASSET_CATALOG = (
    _tushare_raw_entry(
        asset_key="raw_tushare_trade_calendar",
        dataset_id="trade_cal",
        group_name="calendar",
        data_domain=DataDomain.BASIC_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(raw_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)),
        partition_model=PartitionModel.FULL_FILE_RAW_TRADE_CALENDAR,
        source_api="trade_cal",
        source_doc="docs/sources/tushare/股票数据/基础数据/0026_交易日历.md",
        blocking_check_names=RAW_TRADE_CALENDAR_CHECKS,
        batch_grain="single_file",
    ),
    _derived_entry(
        asset_key="silver_trade_calendar",
        dataset_id="trade_cal",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="calendar",
        data_contract="standardized_trade_calendar",
        column_schema=SILVER_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(
            silver_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_TRADE_CALENDAR,
        blocking_check_names=SILVER_TRADE_CALENDAR_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_stock_basic",
        dataset_id="stock_basic",
        group_name="basic",
        data_domain=DataDomain.BASIC_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_BASIC_SCHEMA,
        path_template=lake_path_template(raw_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)),
        partition_model=PartitionModel.FULL_FILE_RAW_STOCK_BASIC,
        source_api="stock_basic",
        source_doc="docs/sources/tushare/股票数据/基础数据/0025_股票基础信息.md",
        blocking_check_names=RAW_STOCK_BASIC_CHECKS,
        batch_grain="single_file",
    ),
    _derived_entry(
        asset_key="silver_stock_basic",
        dataset_id="stock_basic",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="basic",
        data_contract="current_listed_cny_stock_basic_lifecycle",
        column_schema=SILVER_STOCK_BASIC_SCHEMA,
        path_template=lake_path_template(
            silver_stock_basic_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_STOCK_BASIC,
        blocking_check_names=SILVER_STOCK_BASIC_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
    ),
    _derived_entry(
        asset_key="silver_stock_lifecycle",
        dataset_id="stock_lifecycle",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="basic",
        data_contract="historical_cny_stock_lifecycle",
        column_schema=SILVER_STOCK_LIFECYCLE_SCHEMA,
        path_template=lake_path_template(
            silver_stock_lifecycle_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_STOCK_LIFECYCLE,
        blocking_check_names=SILVER_STOCK_LIFECYCLE_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
        notes="Historical CNY stock lifecycle facts, including delisted stocks.",
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_namechange",
        dataset_id="namechange",
        group_name="basic",
        data_domain=DataDomain.BASIC_DATA,
        data_contract="source_mirror_deduplicated_full_snapshot",
        column_schema=RAW_TUSHARE_NAMECHANGE_SCHEMA,
        path_template=lake_path_template(raw_namechange_path(PATH_TEMPLATE_LAKE_ROOT)),
        partition_model=PartitionModel.FULL_FILE_RAW_NAMECHANGE,
        source_api="namechange",
        source_doc="docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md",
        blocking_check_names=RAW_NAMECHANGE_CHECKS,
        batch_grain="single_file",
    ),
    _derived_entry(
        asset_key="silver_namechange",
        dataset_id="namechange",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="basic",
        data_contract="standardized_namechange_event_timeline_full_snapshot",
        column_schema=SILVER_NAMECHANGE_SCHEMA,
        path_template=lake_path_template(silver_namechange_path(PATH_TEMPLATE_LAKE_ROOT)),
        partition_model=PartitionModel.FULL_FILE_SILVER_NAMECHANGE,
        blocking_check_names=SILVER_NAMECHANGE_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
    ),
    _derived_entry(
        asset_key="silver_stock_identity_map",
        dataset_id="stock_identity_map",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="basic",
        data_contract="historical_stock_identity_full_snapshot",
        column_schema=SILVER_STOCK_IDENTITY_MAP_SCHEMA,
        path_template=lake_path_template(
            silver_stock_identity_map_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_STOCK_IDENTITY_MAP,
        blocking_check_names=SILVER_STOCK_IDENTITY_MAP_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_suspend_d",
        dataset_id="suspend_d",
        group_name="quote",
        data_domain=DataDomain.QUOTE_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_suspend_d_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_SUSPEND_D,
        source_api="suspend_d",
        source_doc="docs/sources/tushare/股票数据/行情数据/0214_每日停复牌信息.md",
        blocking_check_names=RAW_SUSPEND_D_CHECKS,
        batch_grain="trade_date",
    ),
    _derived_entry(
        asset_key="silver_stock_suspend_daily",
        dataset_id="suspend_d",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="standardized_stock_suspend_daily",
        column_schema=SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_suspend_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_SUSPEND_DAILY,
        blocking_check_names=SILVER_STOCK_SUSPEND_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_stock_daily",
        dataset_id="daily",
        group_name="quote",
        data_domain=DataDomain.QUOTE_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_STOCK_DAILY,
        source_api="daily",
        source_doc="docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md",
        blocking_check_names=RAW_STOCK_DAILY_CHECKS,
        batch_grain="trade_date",
    ),
    _entry(
        asset_key="raw_tushare_stk_nineturn",
        dataset_id="stk_nineturn",
        layer=AssetLayer.RAW,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        source_system=SourceSystem.TUSHARE,
        data_contract="source_mirror",
        data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
        column_schema=RAW_TUSHARE_STK_NINETURN_SCHEMA,
        path_template=lake_path_template(
            raw_stk_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_STK_NINETURN,
        source_api="stk_nineturn",
        source_doc="docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md",
        ingestion_sources=(
            IngestionSource.TUSHARE_API,
            IngestionSource.PROD_DB_READONLY,
        ),
        default_daily_ingestion_source=IngestionSource.TUSHARE_API,
        bootstrap_sources=(IngestionSource.PROD_DB_READONLY,),
        blocking_check_names=RAW_STK_NINETURN_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        performance_contract=_perf(
            batch_grain="trade_date",
            compute_engine=ComputeEngine.TUSHARE_RESOURCE,
            source_request_policy=(
                "daily_tushare_limit_offset; historical_prod_db_readonly"
            ),
            notes="Daily source is Tushare; prod DB is bootstrap-only.",
        ),
        notes=(
            "Raw preserves source stock codes. Historical bootstrap accepts only "
            "the approved prod DB export manifest."
        ),
    ),
    _derived_entry(
        asset_key="silver_stock_nineturn_daily",
        dataset_id="stock_nineturn_daily",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="canonical_stock_nineturn_daily",
        column_schema=SILVER_STOCK_NINETURN_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_nineturn_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=(
            PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY
        ),
        blocking_check_names=SILVER_STOCK_NINETURN_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes=(
            "Derived from raw_tushare_stk_nineturn and "
            "silver_stock_identity_map; emits latest_ts_code only."
        ),
    ),
    _derived_entry(
        asset_key="silver_stock_daily",
        dataset_id="daily",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="standardized_stock_daily_quote",
        column_schema=SILVER_STOCK_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_DAILY,
        blocking_check_names=SILVER_STOCK_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_adj_factor",
        dataset_id="adj_factor",
        group_name="quote",
        data_domain=DataDomain.QUOTE_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            raw_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_ADJ_FACTOR,
        source_api="adj_factor",
        source_doc="docs/sources/tushare/股票数据/行情数据/0028_复权因子.md",
        blocking_check_names=RAW_ADJ_FACTOR_CHECKS,
        batch_grain="trade_date",
    ),
    _derived_entry(
        asset_key="silver_adj_factor",
        dataset_id="adj_factor",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="standardized_adj_factor",
        column_schema=SILVER_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            silver_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_ADJ_FACTOR,
        blocking_check_names=SILVER_ADJ_FACTOR_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.OLD_LAKE_BOOTSTRAP,),
    ),
    _derived_entry(
        asset_key="gold_stock_daily_qfq",
        dataset_id="stock_daily_qfq",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="gold_stock_daily_forward_adjusted_quote",
        column_schema=GOLD_STOCK_DAILY_QFQ_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_qfq_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ,
        blocking_check_names=GOLD_STOCK_DAILY_QFQ_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes=(
            "Daily qfq reads silver_stock_daily and silver_adj_factor. Historical "
            "bootstrap may use runless full-history materialization events and "
            "recent-window ordinary check events."
        ),
    ),
)


LAKE_ASSET_CATALOG += tuple(
    _entry(
        asset_key=f"raw_stk_mins_{freq}m",
        dataset_id="stk_mins",
        layer=AssetLayer.RAW,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        source_system=SourceSystem.TUSHARE,
        data_contract="source_mirror",
        data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
        column_schema=RAW_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            raw_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_STOCK_MINS,
        source_api="stk_mins",
        source_doc="docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md",
        ingestion_sources=(
            IngestionSource.TUSHARE_API,
            IngestionSource.PROD_DB_READONLY,
            IngestionSource.OLD_LAKE_BOOTSTRAP,
        ),
        default_daily_ingestion_source=IngestionSource.PROD_DB_READONLY,
        bootstrap_sources=(IngestionSource.OLD_LAKE_BOOTSTRAP,),
        blocking_check_names=RAW_STK_MINS_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        performance_contract=_perf(
            batch_grain="freq/trade_date",
            compute_engine=ComputeEngine.DUCKDB_SQL,
            source_request_policy="prod_db_batch_query_per_freq_or_tushare_fallback",
            notes="Raw source freqs remain limited to 1/5/15/30/60.",
        ),
    )
    for freq in (1, 5, 15, 30, 60)
)

LAKE_ASSET_CATALOG += tuple(
    _derived_entry(
        asset_key=f"silver_stk_mins_{freq}m",
        dataset_id="stk_mins",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="standardized_stock_minute_bars",
        column_schema=SILVER_STK_MINS_SCHEMA,
        path_template=lake_path_template(
            silver_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_STOCK_MINS,
        blocking_check_names=SILVER_STK_MINS_CHECKS,
        batch_grain="freq/trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.OLD_LAKE_BOOTSTRAP,),
        notes="Silver source freqs remain limited to 1/5/15/30/60.",
    )
    for freq in (1, 5, 15, 30, 60)
)

LAKE_ASSET_CATALOG += tuple(
    _derived_entry(
        asset_key=f"gold_stk_mins_qfq_{freq}m",
        dataset_id="stk_mins_qfq",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_minute_bars",
        column_schema=GOLD_STK_MINS_QFQ_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_TS_CODE,
                PATH_TEMPLATE_YEAR,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_STOCK_YEAR_FILE,
        blocking_check_names=GOLD_STK_MINS_QFQ_NATIVE_CHECKS,
        batch_grain="freq/year",
        write_policy=WritePolicy.STOCK_YEAR_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(
            IngestionSource.OLD_LAKE_BOOTSTRAP,
            IngestionSource.DERIVED_FROM_ASSETS,
        ),
        notes="Native qfq freqs are generated from silver stk_mins and adj_factor.",
    )
    for freq in (1, 5, 15, 30, 60)
)

LAKE_ASSET_CATALOG += tuple(
    _derived_entry(
        asset_key=f"gold_stk_mins_qfq_{freq}m",
        dataset_id="stk_mins_qfq",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_minute_bars_derived_from_qfq_source",
        column_schema=GOLD_STK_MINS_QFQ_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_TS_CODE,
                PATH_TEMPLATE_YEAR,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_STOCK_YEAR_FILE,
        blocking_check_names=GOLD_STK_MINS_QFQ_DERIVED_CHECKS,
        batch_grain="freq/year",
        write_policy=WritePolicy.STOCK_YEAR_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="Derived qfq freqs read gold qfq source freqs only: 90m from 30m, 120m from 60m.",
    )
    for freq in (90, 120)
)

LAKE_ASSET_CATALOG += tuple(
    _derived_entry(
        asset_key=f"gold_stk_mins_qfq_macd_kdj_{freq}m",
        dataset_id="stk_mins_qfq_macd_kdj",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_minute_macd_kdj_indicators",
        column_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_macd_kdj_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_TS_CODE,
                PATH_TEMPLATE_YEAR,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STOCK_YEAR_FILE,
        blocking_check_names=GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
        batch_grain="freq/year",
        write_policy=WritePolicy.STOCK_YEAR_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="MACD/KDJ indicator rows are derived only from seven-frequency gold qfq minute bars.",
    )
    for freq in (1, 5, 15, 30, 60, 90, 120)
)

LAKE_ASSET_CATALOG += tuple(
    _derived_entry(
        asset_key=f"gold_stk_mins_qfq_macd_kdj_state_{freq}m",
        dataset_id="stk_mins_qfq_macd_kdj_state",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_minute_macd_kdj_indicator_state",
        column_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_macd_kdj_state_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_MACD_KDJ_STATE,
        blocking_check_names=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
        batch_grain="freq/trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="State rows persist the last recursive MACD/KDJ state per ts_code/freq/trade_date for future incremental computation.",
    )
    for freq in (1, 5, 15, 30, 60, 90, 120)
)

LAKE_ASSET_CATALOG += (
    _tushare_raw_entry(
        asset_key="raw_tushare_index_basic",
        dataset_id="index_basic",
        group_name="index",
        data_domain=DataDomain.INDEX_TOPIC,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_INDEX_BASIC_SCHEMA,
        path_template=lake_path_template(raw_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)),
        partition_model=PartitionModel.FULL_FILE_RAW_INDEX_BASIC,
        source_api="index_basic",
        source_doc="docs/sources/tushare/指数专题/0094_指数基本信息.md",
        blocking_check_names=RAW_INDEX_BASIC_CHECKS,
        batch_grain="single_file",
    ),
    _derived_entry(
        asset_key="silver_index_basic",
        dataset_id="index_basic",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        data_contract="effective_index_basic",
        column_schema=SILVER_INDEX_BASIC_SCHEMA,
        path_template=lake_path_template(
            silver_index_basic_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_INDEX_BASIC,
        blocking_check_names=SILVER_INDEX_BASIC_CHECKS,
        batch_grain="single_file",
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
    ),
    _entry(
        asset_key="raw_index_daily",
        dataset_id="index_daily",
        layer=AssetLayer.RAW,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        source_system=SourceSystem.PROD_CORE_DB,
        data_contract="prod_core_index_daily_by_date",
        data_contract_source=DataContractSource.PROD_SERVING_CONTRACT,
        column_schema=RAW_INDEX_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_index_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_DAILY,
        source_api=None,
        source_doc=None,
        ingestion_sources=(IngestionSource.PROD_DB_READONLY,),
        default_daily_ingestion_source=IngestionSource.PROD_DB_READONLY,
        bootstrap_sources=(),
        blocking_check_names=RAW_INDEX_DAILY_BY_DATE_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        performance_contract=_perf(
            batch_grain="trade_date",
            compute_engine=ComputeEngine.DUCKDB_SQL,
            source_request_policy="prod_core_db_one_readonly_query_per_trade_date",
            notes=(
                "Daily raw partition reads the runtime DG cn_a_index_ts_codes set, "
                "requires full prod serving coverage, and writes one by-date parquet file."
            ),
        ),
    ),
    _derived_entry(
        asset_key="silver_index_daily",
        dataset_id="index_daily",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        data_contract="active_index_daily",
        column_schema=SILVER_INDEX_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_index_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_DAILY,
        blocking_check_names=SILVER_INDEX_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.OLD_LAKE_BOOTSTRAP,),
    ),
    _derived_entry(
        asset_key="gold_market_major_indices_daily",
        dataset_id="market_major_indices_daily",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="market",
        data_contract="market_major_indices_daily",
        column_schema=GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
        path_template=lake_path_template(
            gold_market_major_indices_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_MARKET_MAJOR_INDICES_DAILY,
        blocking_check_names=GOLD_MARKET_MAJOR_INDICES_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    ),
    _derived_entry(
        asset_key="gold_market_breadth_daily",
        dataset_id="market_breadth",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="breadth",
        data_contract="market_breadth_daily",
        column_schema=GOLD_MARKET_BREADTH_DAILY_SCHEMA,
        path_template=lake_path_template(
            gold_market_breadth_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_MARKET_BREADTH,
        blocking_check_names=GOLD_MARKET_BREADTH_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    ),
    _derived_entry(
        asset_key="gold_stock_return_distribution",
        dataset_id="stock_return_distribution",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="breadth",
        data_contract="stock_return_distribution",
        column_schema=GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
        path_template=lake_path_template(
            gold_stock_return_distribution_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_RETURN_DISTRIBUTION,
        blocking_check_names=GOLD_STOCK_RETURN_DISTRIBUTION_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    ),
    _entry(
        asset_key="gold_wealth_market_turnover",
        dataset_id="wealth_market_turnover",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="wealth",
        source_system=SourceSystem.DERIVED,
        data_contract="wealth_market_turnover_snapshot",
        data_contract_source=DataContractSource.DERIVED_CONTRACT,
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        path_template=lake_path_template(
            gold_wealth_market_turnover_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER,
        source_api=None,
        source_doc="wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html",
        ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        default_daily_ingestion_source=IngestionSource.DERIVED_FROM_ASSETS,
        bootstrap_sources=(),
        blocking_check_names=GOLD_WEALTH_MARKET_TURNOVER_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain="one trade_date partition, five stk_mins frequencies",
            compute_engine=ComputeEngine.DUCKDB_SQL,
            source_request_policy="read local silver stk_mins parquet files only",
        ),
    ),
    _entry(
        asset_key="prod_core_wealth_market_turnover",
        dataset_id="wealth_market_turnover",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="wealth",
        source_system=SourceSystem.DERIVED,
        data_contract="core_serving.wealth_market_turnover_snapshot",
        data_contract_source=DataContractSource.DERIVED_CONTRACT,
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        path_template=(
            "postgresql://prod/core_serving.wealth_market_turnover_snapshot"
            "?trade_date={partition_key}"
        ),
        partition_model=PartitionModel.SERVING_TABLE_PROD_WEALTH_MARKET_TURNOVER,
        source_api=None,
        source_doc="wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html",
        ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        default_daily_ingestion_source=IngestionSource.DERIVED_FROM_ASSETS,
        bootstrap_sources=(),
        blocking_check_names=(),
        write_policy=WritePolicy.POSTGRES_TABLE_SYNC,
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain="one trade_date partition, five serving rows",
            compute_engine=ComputeEngine.POSTGRES_SQL,
            source_request_policy=(
                "read one local gold parquet file; write one prod PostgreSQL "
                "core_serving partition"
            ),
        ),
        notes=(
            "Prod PostgreSQL serving sync writes "
            "core_serving.wealth_market_turnover_snapshot from gold lake output."
        ),
    ),
    _derived_entry(
        asset_key="ch_share_fact_market_breadth_daily",
        dataset_id="ch_share_fact_market_breadth_daily",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="serving",
        data_contract="share_fact_market_breadth_daily",
        column_schema=CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
        path_template=None,
        partition_model=PartitionModel.SERVING_TABLE_SERVING_MARKET_BREADTH,
        blocking_check_names=CH_SHARE_FACT_MARKET_BREADTH_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.CLICKHOUSE_TABLE_SYNC,
        compute_engine=ComputeEngine.CLICKHOUSE_CLIENT,
    ),
    _derived_entry(
        asset_key="prod_ch_share_fact_market_breadth_daily",
        dataset_id="prod_ch_share_fact_market_breadth_daily",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="serving",
        data_contract="share_fact_market_breadth_daily_prod_sync",
        column_schema=CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
        path_template=None,
        partition_model=PartitionModel.SERVING_TABLE_SERVING_MARKET_BREADTH,
        blocking_check_names=PROD_CH_SHARE_FACT_MARKET_BREADTH_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.CLICKHOUSE_TABLE_SYNC,
        compute_engine=ComputeEngine.CLICKHOUSE_CLIENT,
        notes="Prod ClickHouse serving sync uses the same table schema contract as the local serving asset.",
    ),
    _entry(
        asset_key="lake_root_health",
        dataset_id="lake_root_health",
        layer=AssetLayer.PLATFORM,
        data_domain=DataDomain.PLATFORM_OBSERVABILITY,
        group_name="platform_observability",
        source_system=SourceSystem.DERIVED,
        data_contract="lake_root_health_v1",
        data_contract_source=DataContractSource.PLATFORM_CONTRACT,
        column_schema=None,
        path_template=None,
        partition_model=PartitionModel.NON_PARTITIONED_PLATFORM_LAKE_ROOT_HEALTH,
        source_api=None,
        source_doc=None,
        ingestion_sources=(IngestionSource.INFRASTRUCTURE_CHECK,),
        default_daily_ingestion_source=None,
        bootstrap_sources=(),
        blocking_check_names=LAKE_ROOT_HEALTH_CHECKS,
        write_policy=WritePolicy.NO_DATA_FILE,
        event_policy=EventPolicy.HEALTH_MATERIALIZATION_ONLY,
        performance_contract=_perf(
            batch_grain="non_partitioned",
            compute_engine=ComputeEngine.FILESYSTEM_CHECK,
            source_request_policy="no_source_requests",
            notes="Infrastructure health materialization does not write parquet.",
        ),
    ),
)


def _index_by_asset_key() -> dict[str, LakeAssetCatalogEntry]:
    index: dict[str, LakeAssetCatalogEntry] = {}
    for entry in LAKE_ASSET_CATALOG:
        if entry.asset_key in index:
            raise ValueError(f"Duplicate lake asset catalog key: {entry.asset_key}")
        index[entry.asset_key] = entry
    return index


def _index_partition_models() -> dict[PartitionModel, PartitionModelDefinition]:
    index: dict[PartitionModel, PartitionModelDefinition] = {}
    for definition in PARTITION_MODEL_DEFINITIONS:
        if definition.model in index:
            raise ValueError(f"Duplicate partition model: {definition.model.value}")
        index[definition.model] = definition
    return index


_CATALOG_BY_ASSET_KEY = _index_by_asset_key()
_PARTITION_MODELS_BY_MODEL = _index_partition_models()


def get_partition_model_definition(
    model: PartitionModel,
) -> PartitionModelDefinition:
    try:
        return _PARTITION_MODELS_BY_MODEL[model]
    except KeyError as error:
        raise KeyError(f"Unknown partition model: {model!r}") from error


def list_lake_asset_catalog_entries() -> tuple[LakeAssetCatalogEntry, ...]:
    return LAKE_ASSET_CATALOG


def get_lake_asset_catalog_entry(asset_key: str) -> LakeAssetCatalogEntry:
    try:
        return _CATALOG_BY_ASSET_KEY[asset_key]
    except KeyError as error:
        raise KeyError(f"Unknown lake asset catalog key: {asset_key!r}") from error


def list_lake_asset_keys() -> tuple[str, ...]:
    return tuple(entry.asset_key for entry in LAKE_ASSET_CATALOG)


def list_lake_asset_entries_by_dataset_id(
    dataset_id: str,
) -> tuple[LakeAssetCatalogEntry, ...]:
    return tuple(entry for entry in LAKE_ASSET_CATALOG if entry.dataset_id == dataset_id)


def _validate_catalog() -> None:
    missing_partition_models = [
        entry.partition_model
        for entry in LAKE_ASSET_CATALOG
        if entry.partition_model not in _PARTITION_MODELS_BY_MODEL
    ]
    if missing_partition_models:
        names = ", ".join(model.value for model in missing_partition_models)
        raise ValueError(f"Catalog entries reference unknown partition models: {names}")


_validate_catalog()
