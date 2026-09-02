"""Dagster Raw and Silver assets for ETF daily market data."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.assets.etf_basic import silver_etf_basic
from orchestrator.defs.io.etf_daily_raw_writer import (
    EtfDailyRawWriteResult,
    write_fund_adj_raw_partition,
    write_fund_daily_raw_partition,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    EtfDailySilverWriteResult,
    write_etf_adj_factor_silver_partition,
    write_etf_daily_silver_partition,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_fund_adj_path,
    raw_fund_daily_path,
    silver_etf_adj_factor_path,
    silver_etf_daily_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_FUND_ADJ_SCHEMA,
    RAW_TUSHARE_FUND_DAILY_SCHEMA,
    SILVER_ETF_ADJ_FACTOR_SCHEMA,
    SILVER_ETF_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_ADJ_FACTOR_DATASET_ID,
    ETF_DAILY_DATASET_ID,
    FUND_ADJ_API_NAME,
    FUND_ADJ_DATASET_ID,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_API_NAME,
    FUND_DAILY_DATASET_ID,
    FUND_DAILY_SOURCE_COLUMNS,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    SILVER_ETF_DAILY_ASSET_KEY,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)

_FUND_DAILY_SOURCE_DOC = "docs/sources/tushare/ETF专题/0127_ETF日线行情.md"
_FUND_ADJ_SOURCE_DOC = "docs/sources/tushare/ETF专题/0199_基金复权因子.md"
_FUND_DAILY_DATA_CONTRACT = "tushare_fund_daily_full_source_mirror"
_FUND_ADJ_DATA_CONTRACT = "tushare_fund_adj_full_source_mirror"
_ETF_DAILY_SILVER_DATA_CONTRACT = "latest_basic_filtered_etf_daily"
_ETF_ADJ_FACTOR_SILVER_DATA_CONTRACT = "latest_basic_filtered_etf_adj_factor"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _materialization_result(result: EtfDailyRawWriteResult) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=result.source_fields,
            extra_metadata=result.to_details(),
        )
    )


def _silver_materialization_result(
    result: EtfDailySilverWriteResult,
) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=(
                FUND_DAILY_SOURCE_COLUMNS
                if result.asset_key == SILVER_ETF_DAILY_ASSET_KEY
                else FUND_ADJ_SOURCE_COLUMNS
            ),
            extra_metadata=result.to_details(),
        )
    )


def _shanghai_today():  # type: ignore[no-untyped-def]
    return datetime.now(_SHANGHAI).date()


@dg.asset(
    name=RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
    partitions_def=cn_a_etf_mins_trade_days,
    group_name="quote",
    tags=build_asset_tags(
        layer=AssetLayer.RAW,
        data_domain=DataDomain.QUOTE_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id=FUND_DAILY_DATASET_ID,
        source_system=SourceSystem.TUSHARE,
        data_contract=_FUND_DAILY_DATA_CONTRACT,
        column_schema=RAW_TUSHARE_FUND_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_fund_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api=FUND_DAILY_API_NAME,
        source_category_path="ETF专题",
        source_doc=_FUND_DAILY_SOURCE_DOC,
        extra_metadata={
            "partition_set": cn_a_etf_mins_trade_days.name,
            "source_scope": "all_source_rows_for_trade_date",
            "write_boundary": "raw_single_partition_atomic_replace",
        },
    ),
    description="按交易日保存 Tushare 返回的全部基金日线源端事实。",
)
def raw_tushare_fund_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    context.log.info(
        "source_fetch_started asset=%s partition=%s",
        RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
        context.partition_key,
    )
    result = write_fund_daily_raw_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        tushare=tushare,
        partition_key=context.partition_key,
        operation_id=context.run_id,
    )
    context.log.info(
        "source_pages_completed asset=%s partition=%s pages=%s requests=%s rows=%s",
        result.asset_key,
        result.partition_key,
        result.page_count,
        result.request_count,
        result.source_row_count,
    )
    context.log.info(
        "candidate_validated asset=%s partition=%s rows=%s hash=%s",
        result.asset_key,
        result.partition_key,
        result.candidate_row_count,
        result.content_hash,
    )
    context.log.info(
        "partition_promoted_or_reused asset=%s partition=%s mode=%s path=%s",
        result.asset_key,
        result.partition_key,
        result.write_mode,
        result.target_path,
    )
    return _materialization_result(result)


@dg.asset(
    name=RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    partitions_def=cn_a_etf_mins_trade_days,
    group_name="quote",
    tags=build_asset_tags(
        layer=AssetLayer.RAW,
        data_domain=DataDomain.QUOTE_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id=FUND_ADJ_DATASET_ID,
        source_system=SourceSystem.TUSHARE,
        data_contract=_FUND_ADJ_DATA_CONTRACT,
        column_schema=RAW_TUSHARE_FUND_ADJ_SCHEMA,
        path_template=lake_path_template(
            raw_fund_adj_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api=FUND_ADJ_API_NAME,
        source_category_path="ETF专题",
        source_doc=_FUND_ADJ_SOURCE_DOC,
        extra_metadata={
            "partition_set": cn_a_etf_mins_trade_days.name,
            "source_scope": "all_source_rows_for_trade_date",
            "write_boundary": "raw_single_partition_atomic_replace",
        },
    ),
    description="按交易日保存 Tushare 返回的全部基金复权因子源端事实。",
)
def raw_tushare_fund_adj(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    context.log.info(
        "source_fetch_started asset=%s partition=%s",
        RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
        context.partition_key,
    )
    result = write_fund_adj_raw_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        tushare=tushare,
        partition_key=context.partition_key,
        operation_id=context.run_id,
    )
    context.log.info(
        "source_pages_completed asset=%s partition=%s pages=%s requests=%s rows=%s",
        result.asset_key,
        result.partition_key,
        result.page_count,
        result.request_count,
        result.source_row_count,
    )
    context.log.info(
        "candidate_validated asset=%s partition=%s rows=%s hash=%s",
        result.asset_key,
        result.partition_key,
        result.candidate_row_count,
        result.content_hash,
    )
    context.log.info(
        "partition_promoted_or_reused asset=%s partition=%s mode=%s path=%s",
        result.asset_key,
        result.partition_key,
        result.write_mode,
        result.target_path,
    )
    return _materialization_result(result)


@dg.asset(
    name=SILVER_ETF_DAILY_ASSET_KEY,
    deps=[raw_tushare_fund_daily, silver_etf_basic],
    partitions_def=cn_a_etf_mins_trade_days,
    group_name="quote",
    tags=build_asset_tags(
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id=ETF_DAILY_DATASET_ID,
        source_system=SourceSystem.DERIVED,
        data_contract=_ETF_DAILY_SILVER_DATA_CONTRACT,
        column_schema=SILVER_ETF_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_etf_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "partition_set": cn_a_etf_mins_trade_days.name,
            "source_asset_key": RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
            "basic_asset_key": silver_etf_basic.key.to_user_string(),
            "source_scope": "latest_ready_basic_filtered_exchange_etf",
            "write_boundary": "silver_single_partition_atomic_replace",
        },
    ),
    description="按最新可用 ETF Basic 筛选场内 ETF，并仅标准化交易日类型。",
)
def silver_etf_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    today = _shanghai_today()
    basic_reference = select_latest_etf_basic_snapshot_reference(
        instance=context.instance,
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        eligibility_as_of=today,
        required_freshness_date=today,
    )
    result = write_etf_daily_silver_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        partition_key=context.partition_key,
        operation_id=context.run_id,
        basic_reference=basic_reference,
    )
    context.log.info(
        "silver_partition_validated asset=%s partition=%s raw=%s selected=%s "
        "rejected=%s basic=%s",
        result.asset_key,
        result.partition_key,
        result.raw_row_count,
        result.selected_row_count,
        result.rejected_row_count,
        result.basic_reference.reference_fingerprint,
    )
    context.log.info(
        "partition_promoted_or_reused asset=%s partition=%s mode=%s path=%s",
        result.asset_key,
        result.partition_key,
        result.write_mode,
        result.target_path,
    )
    return _silver_materialization_result(result)


@dg.asset(
    name=SILVER_ETF_ADJ_FACTOR_ASSET_KEY,
    deps=[raw_tushare_fund_adj, silver_etf_basic],
    partitions_def=cn_a_etf_mins_trade_days,
    group_name="quote",
    tags=build_asset_tags(
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.QUOTE_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id=ETF_ADJ_FACTOR_DATASET_ID,
        source_system=SourceSystem.DERIVED,
        data_contract=_ETF_ADJ_FACTOR_SILVER_DATA_CONTRACT,
        column_schema=SILVER_ETF_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            silver_etf_adj_factor_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "partition_set": cn_a_etf_mins_trade_days.name,
            "source_asset_key": RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
            "basic_asset_key": silver_etf_basic.key.to_user_string(),
            "source_scope": "latest_ready_basic_filtered_exchange_etf",
            "write_boundary": "silver_single_partition_atomic_replace",
        },
    ),
    description="按最新可用 ETF Basic 筛选场内 ETF，并保留源端复权与贴水率。",
)
def silver_etf_adj_factor(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    today = _shanghai_today()
    basic_reference = select_latest_etf_basic_snapshot_reference(
        instance=context.instance,
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        eligibility_as_of=today,
        required_freshness_date=today,
    )
    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        partition_key=context.partition_key,
        operation_id=context.run_id,
        basic_reference=basic_reference,
    )
    context.log.info(
        "silver_partition_validated asset=%s partition=%s raw=%s selected=%s "
        "rejected=%s basic=%s",
        result.asset_key,
        result.partition_key,
        result.raw_row_count,
        result.selected_row_count,
        result.rejected_row_count,
        result.basic_reference.reference_fingerprint,
    )
    context.log.info(
        "partition_promoted_or_reused asset=%s partition=%s mode=%s path=%s",
        result.asset_key,
        result.partition_key,
        result.write_mode,
        result.target_path,
    )
    return _silver_materialization_result(result)


__all__ = [
    "raw_tushare_fund_adj",
    "raw_tushare_fund_daily",
    "silver_etf_adj_factor",
    "silver_etf_daily",
]
