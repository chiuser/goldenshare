"""Read-only catalog registry for active Dagster lake assets."""

from dataclasses import dataclass
from enum import Enum

from orchestrator.defs.catalog.name_mapping import get_dataset_chinese_name
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    PATH_TEMPLATE_TS_CODE,
    PATH_TEMPLATE_YEAR,
    gold_dc_daily_technical_path,
    gold_major_index_mins_technical_path,
    gold_major_index_mins_technical_state_path,
    gold_market_breadth_daily_path,
    gold_market_major_indices_daily_path,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_nineturn_path,
    gold_stk_mins_qfq_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
    gold_stock_return_distribution_path,
    gold_wealth_market_turnover_path,
    lake_path_template,
    raw_adj_factor_path,
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    raw_idx_factor_pro_path,
    raw_index_basic_path,
    raw_index_daily_path,
    raw_index_global_path,
    raw_index_mins_path,
    raw_major_index_mins_path,
    raw_namechange_path,
    raw_stk_mins_path,
    raw_stk_nineturn_path,
    raw_stock_basic_path,
    raw_stock_daily_path,
    raw_suspend_d_path,
    raw_trade_calendar_path,
    silver_adj_factor_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_industry_hierarchy_path,
    silver_dc_member_path,
    silver_index_basic_path,
    silver_index_daily_path,
    silver_index_factor_pro_path,
    silver_index_global_path,
    silver_index_mins_path,
    silver_major_index_mins_path,
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
    CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
    CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
    GOLD_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
    GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_SCHEMA,
    RAW_INDEX_DAILY_SCHEMA,
    RAW_INDEX_GLOBAL_SCHEMA,
    RAW_INDEX_MINS_SCHEMA,
    RAW_MAJOR_INDEX_MINS_SCHEMA,
    RAW_STK_MINS_SCHEMA,
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
    RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
    RAW_TUSHARE_INDEX_BASIC_SCHEMA,
    RAW_TUSHARE_NAMECHANGE_SCHEMA,
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    RAW_TUSHARE_STOCK_DAILY_SCHEMA,
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
    SILVER_DC_INDEX_SCHEMA,
    SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
    SILVER_DC_MEMBER_SCHEMA,
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_INDEX_FACTOR_PRO_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
    SILVER_MAJOR_INDEX_MINS_SCHEMA,
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
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_REQUEST_POLICY_NAME,
    DC_INDEX_REQUEST_POLICY_NAME,
    DC_MEMBER_REQUEST_POLICY_NAME,
    RAW_DC_DAILY_CHECKS,
    RAW_DC_INDEX_CHECKS,
    RAW_DC_MEMBER_CHECKS,
    SILVER_DC_DAILY_CHECKS,
    SILVER_DC_INDEX_CHECKS,
    SILVER_DC_MEMBER_CHECKS,
)
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_CHECKS,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    CH_DC_DAILY_TECHNICAL_CHECKS,
    PROD_CH_DC_DAILY_TECHNICAL_CHECKS,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_RAW_CHECKS,
    IDX_FACTOR_PRO_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_RAW_CHECKS,
    INDEX_GLOBAL_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_FREQS,
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
    major_index_mins_technical_state_asset_key,
    major_index_mins_technical_state_checks,
)
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
    FULL_FILE_SILVER_DC_INDUSTRY_HIERARCHY = "full_file_silver_dc_industry_hierarchy"
    FULL_FILE_RAW_INDEX_BASIC = "full_file_raw_index_basic"
    FULL_FILE_SILVER_INDEX_BASIC = "full_file_silver_index_basic"

    TRADE_DATE_PARTITION_RAW_STOCK_DAILY = "trade_date_partition_raw_stock_daily"
    TRADE_DATE_PARTITION_SILVER_STOCK_DAILY = "trade_date_partition_silver_stock_daily"
    TRADE_DATE_PARTITION_RAW_STK_NINETURN = "trade_date_partition_raw_stk_nineturn"
    TRADE_DATE_PARTITION_SILVER_STOCK_NINETURN_DAILY = (
        "trade_date_partition_silver_stock_nineturn_daily"
    )
    TRADE_DATE_PARTITION_RAW_ADJ_FACTOR = "trade_date_partition_raw_adj_factor"
    TRADE_DATE_PARTITION_SILVER_ADJ_FACTOR = "trade_date_partition_silver_adj_factor"
    TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ = (
        "trade_date_partition_gold_stock_daily_qfq"
    )
    TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ_NINETURN = (
        "trade_date_partition_gold_stock_daily_qfq_nineturn"
    )
    TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_NINETURN = (
        "trade_date_partition_gold_stock_mins_qfq_nineturn"
    )
    TRADE_DATE_PARTITION_GOLD_DC_DAILY_TECHNICAL = (
        "trade_date_partition_gold_dc_daily_technical"
    )
    TRADE_DATE_PARTITION_RAW_SUSPEND_D = "trade_date_partition_raw_suspend_d"
    TRADE_DATE_PARTITION_SILVER_STOCK_SUSPEND_DAILY = (
        "trade_date_partition_silver_stock_suspend_daily"
    )
    TRADE_DATE_PARTITION_RAW_INDEX_DAILY = "trade_date_partition_raw_index_daily"
    TRADE_DATE_PARTITION_SILVER_INDEX_DAILY = "trade_date_partition_silver_index_daily"
    TRADE_DATE_PARTITION_RAW_INDEX_GLOBAL = "trade_date_partition_raw_index_global"
    TRADE_DATE_PARTITION_SILVER_INDEX_GLOBAL = (
        "trade_date_partition_silver_index_global"
    )
    TRADE_DATE_PARTITION_RAW_INDEX_MINS = "trade_date_partition_raw_index_mins"
    TRADE_DATE_PARTITION_SILVER_INDEX_MINS = "trade_date_partition_silver_index_mins"
    TRADE_DATE_PARTITION_RAW_MAJOR_INDEX_MINS = (
        "trade_date_partition_raw_major_index_mins"
    )
    TRADE_DATE_PARTITION_SILVER_MAJOR_INDEX_MINS = (
        "trade_date_partition_silver_major_index_mins"
    )
    TRADE_DATE_PARTITION_RAW_IDX_FACTOR_PRO = (
        "trade_date_partition_raw_idx_factor_pro"
    )
    TRADE_DATE_PARTITION_SILVER_INDEX_FACTOR_PRO = (
        "trade_date_partition_silver_index_factor_pro"
    )
    TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL = (
        "trade_date_partition_gold_major_index_mins_technical"
    )
    TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE = (
        "trade_date_partition_gold_major_index_mins_technical_state"
    )
    TRADE_DATE_PARTITION_RAW_DC_INDEX = "trade_date_partition_raw_dc_index"
    TRADE_DATE_PARTITION_RAW_DC_MEMBER = "trade_date_partition_raw_dc_member"
    TRADE_DATE_PARTITION_RAW_DC_DAILY = "trade_date_partition_raw_dc_daily"
    TRADE_DATE_PARTITION_SILVER_DC_INDEX = "trade_date_partition_silver_dc_index"
    TRADE_DATE_PARTITION_SILVER_DC_MEMBER = "trade_date_partition_silver_dc_member"
    TRADE_DATE_PARTITION_SILVER_DC_DAILY = "trade_date_partition_silver_dc_daily"
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
    SERVING_TABLE_PROD_WEALTH_SECTOR_HIERARCHY = (
        "serving_table_prod_wealth_sector_hierarchy"
    )
    SERVING_TABLE_PROD_STOCK_DAILY_QFQ_NINETURN = (
        "serving_table_prod_stock_daily_qfq_nineturn"
    )

    SERVING_TABLE_SERVING_MARKET_BREADTH = "serving_table_serving_market_breadth"
    SERVING_TABLE_SERVING_DC_DAILY_TECHNICAL = (
        "serving_table_serving_dc_daily_technical"
    )
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


RAW_TRADE_CALENDAR_CHECKS = ("raw_trade_calendar_contract_check",)
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
SILVER_DC_INDUSTRY_HIERARCHY_CHECKS = ("silver_dc_industry_hierarchy_core_check",)
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
GOLD_STOCK_DAILY_QFQ_CHECKS = ("gold_stock_daily_qfq_contract_check",)
GOLD_STOCK_DAILY_QFQ_NINETURN_CHECKS = (
    "gold_stock_daily_qfq_nineturn_integrity_check",
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
    "gold_stk_mins_qfq_source_coverage_check",
)
GOLD_STK_MINS_QFQ_DERIVED_CHECKS = (
    "gold_stk_mins_qfq_derived_source_coverage_check",
    *GOLD_STK_MINS_QFQ_BASE_CHECKS,
)
GOLD_STK_MINS_QFQ_NINETURN_CHECKS_BY_FREQ = {
    freq: (f"gold_stk_mins_qfq_nineturn_{freq}m_integrity_check",)
    for freq in (30, 60, 90, 120)
}
GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS = (
    "gold_stk_mins_qfq_macd_kdj_contract_check",
    "gold_stk_mins_qfq_macd_kdj_source_coverage_check",
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
LAKE_ROOT_HEALTH_CHECKS = ("lake_root_health_ready",)


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
        PartitionModel.FULL_FILE_SILVER_DC_INDUSTRY_HIERARCHY,
        PartitionModelFamily.FULL_FILE,
        AssetLayer.SILVER,
        "dc_industry_hierarchy",
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
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ_NINETURN,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stock_daily_qfq_nineturn",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_NINETURN,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "stk_mins_qfq_nineturn",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_DC_DAILY_TECHNICAL,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "dc_daily_technical",
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
        "trade_date",
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
        PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_GLOBAL,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "index_global",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="自然日分区；允许海外市场尚未发布时生成固定 schema 空文件。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_GLOBAL,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "index_global",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="自然日分区；Silver 与 Raw 同日对齐，允许空分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "index_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="指数分钟线五个源频率共用专属交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "index_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="指数分钟线 Silver 原生及派生频率共用专属交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_MAJOR_INDEX_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "major_index_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="主要指数分钟线五个源频率共用专属交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_MAJOR_INDEX_MINS,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "major_index_mins",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="主要指数分钟线 Silver 原生及派生频率共用专属交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_IDX_FACTOR_PRO,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "idx_factor_pro",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="日级指数技术因子使用独立主要指数技术因子交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_FACTOR_PRO,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "index_factor_pro",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="Silver 与 Raw 共用主要指数技术因子交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "major_index_mins_technical",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="七个分钟频率共用主要指数分钟线交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.GOLD,
        "major_index_mins_technical_state",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
        notes="技术指标 state 与同频 technical 共用主要指数分钟线交易日分区。",
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_DC_INDEX,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "dc_index",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_DC_MEMBER,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "dc_member",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_RAW_DC_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.RAW,
        "dc_daily",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_INDEX,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "dc_index",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_MEMBER,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "dc_member",
        "trade_date",
        PartitionPhysicalLayout.PARTITION_FILE,
    ),
    _model(
        PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_DAILY,
        PartitionModelFamily.TRADE_DATE_PARTITION,
        AssetLayer.SILVER,
        "dc_daily",
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
        PartitionModel.SERVING_TABLE_PROD_WEALTH_SECTOR_HIERARCHY,
        PartitionModelFamily.SERVING_TABLE,
        AssetLayer.SERVING,
        "wealth_sector_hierarchy",
        None,
        PartitionPhysicalLayout.POSTGRES_TABLE,
        notes="Prod PostgreSQL full-snapshot hierarchy serving table sync.",
    ),
    _model(
        PartitionModel.SERVING_TABLE_PROD_STOCK_DAILY_QFQ_NINETURN,
        PartitionModelFamily.SERVING_TABLE,
        AssetLayer.SERVING,
        "stock_daily_qfq_nineturn",
        "trade_date",
        PartitionPhysicalLayout.POSTGRES_TABLE,
        notes="Prod PostgreSQL QFQ nine-turn serving sync partitioned by trade_date.",
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
        PartitionModel.SERVING_TABLE_SERVING_DC_DAILY_TECHNICAL,
        PartitionModelFamily.SERVING_TABLE,
        AssetLayer.SERVING,
        "board_fact_technical",
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
    bootstrap_sources: tuple[IngestionSource, ...] = (),
    source_request_policy: str = "tushare_request_per_asset_unit",
    performance_notes: str = "",
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
        bootstrap_sources=bootstrap_sources,
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
            source_request_policy=source_request_policy,
            notes=performance_notes,
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
        path_template=lake_path_template(
            raw_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
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
        path_template=lake_path_template(
            silver_namechange_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
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
    _entry(
        asset_key="silver_dc_industry_hierarchy",
        dataset_id="dc_industry_hierarchy",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.BASIC_DATA,
        group_name="board",
        source_system=SourceSystem.SEED,
        data_contract="eastmoney_dc_industry_hierarchy_with_board_codes_full_snapshot",
        data_contract_source=DataContractSource.SEED_CONTRACT,
        column_schema=SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
        path_template=lake_path_template(
            silver_dc_industry_hierarchy_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        partition_model=PartitionModel.FULL_FILE_SILVER_DC_INDUSTRY_HIERARCHY,
        source_api=None,
        source_doc=None,
        ingestion_sources=(IngestionSource.SEED_FILE,),
        default_daily_ingestion_source=None,
        bootstrap_sources=(),
        blocking_check_names=SILVER_DC_INDUSTRY_HIERARCHY_CHECKS,
        write_policy=WritePolicy.SINGLE_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain="full_snapshot",
            compute_engine=ComputeEngine.DUCKDB_SQL,
            source_request_policy="manual_seed_and_single_reference_file",
            notes=(
                "Manual snapshot reads one versioned seed CSV and one explicitly selected "
                "silver_dc_index reference partition."
            ),
        ),
        notes="分类事实来自版本化东财行业层级 seed；silver_dc_index 仅补齐当前 BK 代码。",
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
            silver_stock_daily_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
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
    _derived_entry(
        asset_key="gold_stock_daily_qfq_nineturn",
        dataset_id="stock_daily_qfq_nineturn",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_daily_nineturn",
        column_schema=GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_qfq_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=(
            PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ_NINETURN
        ),
        blocking_check_names=GOLD_STOCK_DAILY_QFQ_NINETURN_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="Fixed-formula non-repainting nine-turn output derived from daily QFQ bars.",
    ),
    _derived_entry(
        asset_key="gold_dc_daily_technical",
        dataset_id="dc_daily_technical",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="board",
        data_contract="gold_dc_daily_technical",
        column_schema=GOLD_DC_DAILY_TECHNICAL_SCHEMA,
        path_template=lake_path_template(
            gold_dc_daily_technical_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_DC_DAILY_TECHNICAL,
        blocking_check_names=DC_DAILY_TECHNICAL_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes=(
            "Single Gold technical-indicator asset over silver_dc_daily. "
            "MA/BOLL warmup remains NULL; formula checks stay in fixtures and "
            "the single core contract check, not separate high-cardinality checks."
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
        asset_key=f"gold_stk_mins_qfq_nineturn_{freq}m",
        dataset_id="stk_mins_qfq_nineturn",
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        data_contract="qfq_stock_minute_nineturn",
        column_schema=GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=(
            PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_MINS_QFQ_NINETURN
        ),
        blocking_check_names=GOLD_STK_MINS_QFQ_NINETURN_CHECKS_BY_FREQ[freq],
        batch_grain="freq/trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="Fixed-formula non-repainting nine-turn output derived from same-frequency QFQ bars.",
    )
    for freq in (30, 60, 90, 120)
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
            silver_index_daily_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_DAILY,
        blocking_check_names=SILVER_INDEX_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.OLD_LAKE_BOOTSTRAP,),
    ),
    _tushare_raw_entry(
        asset_key="raw_index_global",
        dataset_id="index_global",
        group_name="index",
        data_domain=DataDomain.INDEX_TOPIC,
        data_contract="tushare_index_global_raw_by_trade_date",
        column_schema=RAW_INDEX_GLOBAL_SCHEMA,
        path_template=lake_path_template(
            raw_index_global_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_GLOBAL,
        source_api="index_global",
        source_doc="docs/sources/tushare/指数专题/0211_国际指数.md",
        blocking_check_names=INDEX_GLOBAL_RAW_CHECKS,
        batch_grain="one_date_one_step",
        bootstrap_sources=(IngestionSource.TUSHARE_API,),
        source_request_policy="index_global_bounded_step_pagination",
        performance_notes=(
            "One natural date and one probe step per run; five steps are "
            "serialized and each step uses bounded pagination. Empty source "
            "observations are valid and do not imply 21-code coverage."
        ),
    ),
    _derived_entry(
        asset_key="silver_index_global",
        dataset_id="index_global",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        data_contract="silver_index_global_by_trade_date",
        column_schema=SILVER_INDEX_GLOBAL_SCHEMA,
        path_template=lake_path_template(
            silver_index_global_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_GLOBAL,
        blocking_check_names=INDEX_GLOBAL_SILVER_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes=(
            "Reads only same-date Raw; empty natural-day Raw/Silver partitions "
            "are valid when the source published no rows."
        ),
    ),
    *tuple(
        _entry(
            asset_key=f"raw_index_mins_{freq}m",
            dataset_id="index_mins",
            layer=AssetLayer.RAW,
            data_domain=DataDomain.QUOTE_DATA,
            group_name="index",
            source_system=SourceSystem.PROD_CORE_DB,
            data_contract="prod_core_index_mins_by_frequency_trade_date",
            data_contract_source=DataContractSource.PROD_SERVING_CONTRACT,
            column_schema=RAW_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                raw_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    f"{freq}min",
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_INDEX_MINS,
            source_api=None,
            source_doc="docs/sources/tushare/指数专题/0419_股票历史分钟行情.md",
            ingestion_sources=(IngestionSource.PROD_DB_READONLY,),
            default_daily_ingestion_source=IngestionSource.PROD_DB_READONLY,
            bootstrap_sources=(IngestionSource.PROD_DB_READONLY,),
            blocking_check_names=(f"raw_index_mins_{freq}m_core_check",),
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            performance_contract=_perf(
                batch_grain="freq/trade_date",
                compute_engine=ComputeEngine.DUCKDB_SQL,
                source_request_policy="prod_db_one_readonly_range_query_per_frequency",
                notes=(
                    "One read-only Prod range query per frequency; active pool "
                    "exact-code validation occurs before staging promotion."
                ),
            ),
        )
        for freq in (1, 5, 15, 30, 60)
    ),
    *tuple(
        _derived_entry(
            asset_key=f"silver_index_mins_{freq}m",
            dataset_id="index_mins",
            layer=AssetLayer.SILVER,
            data_domain=DataDomain.QUOTE_DATA,
            group_name="index",
            data_contract="standardized_index_minute_bars",
            column_schema=SILVER_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                silver_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    f"{freq}min",
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_MINS,
            blocking_check_names=(f"silver_index_mins_{freq}m_core_check",),
            batch_grain="freq/trade_date",
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
            notes=(
                "Native frequencies preserve source vwap; derived 90m/120m "
                "use fixed complete windows and write vwap as NULL."
            ),
        )
        for freq in (1, 5, 15, 30, 60, 90, 120)
    ),
    *tuple(
        _entry(
            asset_key=f"raw_major_index_mins_{freq}m",
            dataset_id="major_index_mins",
            layer=AssetLayer.RAW,
            data_domain=DataDomain.QUOTE_DATA,
            group_name="index",
            source_system=SourceSystem.TUSHARE,
            data_contract="tushare_major_index_mins_exact_session",
            data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
            column_schema=RAW_MAJOR_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                raw_major_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    f"{freq}min",
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_MAJOR_INDEX_MINS,
            source_api="idx_mins",
            source_doc="docs/sources/tushare/指数专题/0419_股票历史分钟行情.md",
            ingestion_sources=(IngestionSource.TUSHARE_API,),
            default_daily_ingestion_source=IngestionSource.TUSHARE_API,
            bootstrap_sources=(IngestionSource.TUSHARE_API,),
            blocking_check_names=(f"raw_major_index_mins_{freq}m_core_check",),
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            performance_contract=_perf(
                batch_grain="freq/trade_date",
                compute_engine=ComputeEngine.TUSHARE_RESOURCE,
                source_request_policy="bounded_code_pages_11_codes_per_frequency",
                notes=(
                    "Explicit fields and bounded pagination; exact code/session "
                    "validation occurs before staging promotion."
                ),
            ),
        )
        for freq in (1, 5, 15, 30, 60)
    ),
    *tuple(
        _derived_entry(
            asset_key=f"silver_major_index_mins_{freq}m",
            dataset_id="major_index_mins",
            layer=AssetLayer.SILVER,
            data_domain=DataDomain.QUOTE_DATA,
            group_name="index",
            data_contract="standardized_major_index_minute_bars",
            column_schema=SILVER_MAJOR_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                silver_major_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    f"{freq}min",
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_MAJOR_INDEX_MINS,
            blocking_check_names=(f"silver_major_index_mins_{freq}m_core_check",),
            batch_grain="freq/trade_date",
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
            notes=(
                "Native frequencies preserve source vwap; 90m/120m use "
                "exchange-aware complete windows and NULL vwap."
            ),
        )
        for freq in (1, 5, 15, 30, 60, 90, 120)
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_dc_index",
        dataset_id="dc_index",
        group_name="board",
        data_domain=DataDomain.QUOTE_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        path_template=lake_path_template(
            raw_dc_index_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_DC_INDEX,
        source_api="dc_index",
        source_doc="docs/sources/tushare/股票数据/打板专题数据/0362_东方财富概念板块.md",
        blocking_check_names=RAW_DC_INDEX_CHECKS,
        batch_grain="trade_date",
        bootstrap_sources=(IngestionSource.TUSHARE_API,),
        source_request_policy=DC_INDEX_REQUEST_POLICY_NAME,
        performance_notes="Three idx_type requests per trade_date with bounded pagination.",
    ),
    _entry(
        asset_key="raw_tushare_dc_member",
        dataset_id="dc_member",
        layer=AssetLayer.RAW,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="board",
        source_system=SourceSystem.TUSHARE,
        data_contract="source_mirror_prod_bootstrap_tushare_daily",
        data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
        column_schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        path_template=lake_path_template(
            raw_dc_member_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_DC_MEMBER,
        source_api="dc_member",
        source_doc="docs/sources/tushare/股票数据/打板专题数据/0363_东方财富板块成分.md",
        ingestion_sources=(
            IngestionSource.TUSHARE_API,
            IngestionSource.PROD_DB_READONLY,
        ),
        default_daily_ingestion_source=IngestionSource.TUSHARE_API,
        bootstrap_sources=(IngestionSource.PROD_DB_READONLY,),
        blocking_check_names=RAW_DC_MEMBER_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        performance_contract=_perf(
            batch_grain="trade_date",
            compute_engine=ComputeEngine.TUSHARE_RESOURCE,
            source_request_policy=DC_MEMBER_REQUEST_POLICY_NAME,
            notes=(
                "Daily writer must explicitly use the approved bounded request "
                "policy; historical bootstrap is read-only prod DB export."
            ),
        ),
        notes=(
            "The asset key names the Tushare contract family. Bootstrap partitions "
            "must record prod_db_readonly_export in materialization metadata."
        ),
    ),
    _tushare_raw_entry(
        asset_key="raw_tushare_dc_daily",
        dataset_id="dc_daily",
        group_name="board",
        data_domain=DataDomain.QUOTE_DATA,
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_dc_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_DC_DAILY,
        source_api="dc_daily",
        source_doc="docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md",
        blocking_check_names=RAW_DC_DAILY_CHECKS,
        batch_grain="trade_date",
        bootstrap_sources=(IngestionSource.TUSHARE_API,),
        source_request_policy=DC_DAILY_REQUEST_POLICY_NAME,
        performance_notes="One trade_date request with bounded pagination.",
    ),
    _derived_entry(
        asset_key="silver_dc_index",
        dataset_id="dc_index",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="board",
        data_contract="standardized_dc_index",
        column_schema=SILVER_DC_INDEX_SCHEMA,
        path_template=lake_path_template(
            silver_dc_index_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_INDEX,
        blocking_check_names=SILVER_DC_INDEX_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
    ),
    _derived_entry(
        asset_key="silver_dc_member",
        dataset_id="dc_member",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="board",
        data_contract="standardized_dc_member",
        column_schema=SILVER_DC_MEMBER_SCHEMA,
        path_template=lake_path_template(
            silver_dc_member_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_MEMBER,
        blocking_check_names=SILVER_DC_MEMBER_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
    ),
    _derived_entry(
        asset_key="silver_dc_daily",
        dataset_id="dc_daily",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="board",
        data_contract="standardized_dc_daily",
        column_schema=SILVER_DC_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_dc_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_DC_DAILY,
        blocking_check_names=SILVER_DC_DAILY_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
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
    _entry(
        asset_key="prod_core_wealth_sector_hierarchy",
        dataset_id="dc_industry_hierarchy",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.BASIC_DATA,
        group_name="wealth",
        source_system=SourceSystem.SEED,
        data_contract="core_serving.wealth_sector_hierarchy",
        data_contract_source=DataContractSource.SEED_CONTRACT,
        column_schema=PROD_CORE_WEALTH_SECTOR_HIERARCHY_SCHEMA,
        path_template=(
            "postgresql://prod/core_serving.wealth_sector_hierarchy"
        ),
        partition_model=PartitionModel.SERVING_TABLE_PROD_WEALTH_SECTOR_HIERARCHY,
        source_api=None,
        source_doc=(
            "wealth/docs/pages/market-overview/"
            "sector-overview-low-level-design-v2.md"
        ),
        ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        default_daily_ingestion_source=None,
        bootstrap_sources=(),
        blocking_check_names=(),
        write_policy=WritePolicy.POSTGRES_TABLE_SYNC,
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain="one full snapshot, exactly 496 serving rows",
            compute_engine=ComputeEngine.POSTGRES_SQL,
            source_request_policy=(
                "read one fixed Silver hierarchy parquet file; write only "
                "core_serving.wealth_sector_hierarchy"
            ),
        ),
        notes=(
            "Explicit manual publisher for the approved Silver Eastmoney hierarchy; "
            "no Heat dependency or automation."
        ),
    ),
    _entry(
        asset_key="prod_core_stock_daily_qfq_nineturn",
        dataset_id="stock_daily_qfq_nineturn",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.QUOTE_DATA,
        group_name="quote",
        source_system=SourceSystem.DERIVED,
        data_contract="core_serving.equity_qfq_nineturn_daily",
        data_contract_source=DataContractSource.DERIVED_CONTRACT,
        column_schema=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
        path_template=(
            "postgresql://prod/core_serving.equity_qfq_nineturn_daily"
            "?trade_date={partition_key}"
        ),
        partition_model=(
            PartitionModel.SERVING_TABLE_PROD_STOCK_DAILY_QFQ_NINETURN
        ),
        source_api=None,
        source_doc=(
            "wealth/docs/system/"
            "detail-page-nine-turn-integration-low-level-design-v1.md"
        ),
        ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        default_daily_ingestion_source=IngestionSource.DERIVED_FROM_ASSETS,
        bootstrap_sources=(),
        blocking_check_names=(
            "prod_core_stock_daily_qfq_nineturn_partition_check",
        ),
        write_policy=WritePolicy.POSTGRES_TABLE_SYNC,
        event_policy=EventPolicy.DAGSTER_RUN_ONLY,
        performance_contract=_perf(
            batch_grain="one trade_date partition, full stock universe",
            compute_engine=ComputeEngine.POSTGRES_SQL,
            source_request_policy=(
                "read one local Gold QFQ nine-turn partition; write one prod "
                "PostgreSQL core_serving partition"
            ),
        ),
        notes=(
            "Publishes autonomous QFQ nine-turn facts only; never consumes or "
            "falls back to the Tushare nine-turn dataset."
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
    _derived_entry(
        asset_key="ch_dc_daily_technical",
        dataset_id="ch_dc_daily_technical",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="serving",
        data_contract="gold_dc_daily_technical_clickhouse_serving",
        column_schema=CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
        path_template=None,
        partition_model=PartitionModel.SERVING_TABLE_SERVING_DC_DAILY_TECHNICAL,
        blocking_check_names=CH_DC_DAILY_TECHNICAL_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.CLICKHOUSE_TABLE_SYNC,
        compute_engine=ComputeEngine.CLICKHOUSE_CLIENT,
    ),
    _derived_entry(
        asset_key="prod_ch_dc_daily_technical",
        dataset_id="prod_ch_dc_daily_technical",
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.DERIVED_METRIC,
        group_name="serving",
        data_contract="gold_dc_daily_technical_prod_clickhouse_sync",
        column_schema=CH_DC_DAILY_TECHNICAL_SERVING_SCHEMA,
        path_template=None,
        partition_model=PartitionModel.SERVING_TABLE_SERVING_DC_DAILY_TECHNICAL,
        blocking_check_names=PROD_CH_DC_DAILY_TECHNICAL_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.CLICKHOUSE_TABLE_SYNC,
        compute_engine=ComputeEngine.CLICKHOUSE_CLIENT,
        notes="Prod ClickHouse serving copy uses the local ClickHouse serving rows as its source.",
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

LAKE_ASSET_CATALOG += (
    _entry(
        asset_key="raw_tushare_idx_factor_pro",
        dataset_id="idx_factor_pro",
        layer=AssetLayer.RAW,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_idx_factor_pro_approved_daily_major_indices",
        data_contract_source=DataContractSource.TUSHARE_RAW_CONTRACT,
        column_schema=RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
        path_template=lake_path_template(
            raw_idx_factor_pro_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_RAW_IDX_FACTOR_PRO,
        source_api="idx_factor_pro",
        source_doc="docs/sources/tushare/指数专题/0358_指数技术因子(专业版).md",
        ingestion_sources=(IngestionSource.TUSHARE_API,),
        default_daily_ingestion_source=IngestionSource.TUSHARE_API,
        bootstrap_sources=(IngestionSource.TUSHARE_API,),
        blocking_check_names=IDX_FACTOR_PRO_RAW_CHECKS,
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        performance_contract=_perf(
            batch_grain="trade_date",
            compute_engine=ComputeEngine.TUSHARE_RESOURCE,
            source_request_policy="one_trade_date_bounded_pages_filter_11_daily_seed_codes",
            notes=(
                "Daily requests use trade_date plus 8000-row pagination; selection "
                "is limited to the date-effective 11-code daily major-index seed."
            ),
        ),
    ),
    _derived_entry(
        asset_key="silver_index_factor_pro",
        dataset_id="index_factor_pro",
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.INDEX_TOPIC,
        group_name="index",
        data_contract="standardized_index_factor_pro",
        column_schema=SILVER_INDEX_FACTOR_PRO_SCHEMA,
        path_template=lake_path_template(
            silver_index_factor_pro_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        partition_model=PartitionModel.TRADE_DATE_PARTITION_SILVER_INDEX_FACTOR_PRO,
        blocking_check_names=IDX_FACTOR_PRO_SILVER_CHECKS,
        batch_grain="trade_date",
        write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
        event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
        bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
        notes="Pure date cast from the same Raw partition; fields and keys remain identical.",
    ),
    *tuple(
        _derived_entry(
            asset_key=major_index_mins_technical_asset_key(freq),
            dataset_id="major_index_mins_technical",
            layer=AssetLayer.GOLD,
            data_domain=DataDomain.DERIVED_METRIC,
            group_name="index",
            data_contract="major_index_minute_technical_indicators_v1",
            column_schema=GOLD_MAJOR_INDEX_MINS_TECHNICAL_SCHEMA,
            path_template=lake_path_template(
                gold_major_index_mins_technical_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=(
                PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL
            ),
            blocking_check_names=major_index_mins_technical_checks(freq),
            batch_grain="freq/trade_date",
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
            notes=(
                "Derived from the same-frequency Silver date-effective code pool; "
                "the daily major-index seed is not a technical-asset input."
            ),
        )
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
    ),
    *tuple(
        _derived_entry(
            asset_key=major_index_mins_technical_state_asset_key(freq),
            dataset_id="major_index_mins_technical_state",
            layer=AssetLayer.GOLD,
            data_domain=DataDomain.DERIVED_METRIC,
            group_name="index",
            data_contract="major_index_minute_technical_state_v1",
            column_schema=GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE_SCHEMA,
            path_template=lake_path_template(
                gold_major_index_mins_technical_state_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            partition_model=(
                PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_MINS_TECHNICAL_STATE
            ),
            blocking_check_names=major_index_mins_technical_state_checks(freq),
            batch_grain="freq/trade_date",
            write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
            event_policy=EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL,
            bootstrap_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
            notes=(
                "Persists recursive state for exactly the same date-effective "
                "Silver code pool and frequency as the paired technical asset."
            ),
        )
        for freq in MAJOR_INDEX_MINS_TECHNICAL_FREQS
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
    return tuple(
        entry for entry in LAKE_ASSET_CATALOG if entry.dataset_id == dataset_id
    )


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
