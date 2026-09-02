"""Dagster Raw assets for fund daily bars and fund adjustment factors."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.io.etf_daily_raw_writer import (
    EtfDailyRawWriteResult,
    write_fund_adj_raw_partition,
    write_fund_daily_raw_partition,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_fund_adj_path,
    raw_fund_daily_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_FUND_ADJ_SCHEMA,
    RAW_TUSHARE_FUND_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.etf_daily import (
    FUND_ADJ_API_NAME,
    FUND_ADJ_DATASET_ID,
    FUND_DAILY_API_NAME,
    FUND_DAILY_DATASET_ID,
    RAW_TUSHARE_FUND_ADJ_ASSET_KEY,
    RAW_TUSHARE_FUND_DAILY_ASSET_KEY,
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


def _materialization_result(result: EtfDailyRawWriteResult) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=result.source_fields,
            extra_metadata=result.to_details(),
        )
    )


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


__all__ = ["raw_tushare_fund_adj", "raw_tushare_fund_daily"]
