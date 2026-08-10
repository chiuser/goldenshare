"""Dagster Raw asset for Tushare index technical factors."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.io.idx_factor_pro_raw_writer import (
    write_idx_factor_pro_raw_partition,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_idx_factor_pro_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_API_NAME,
    IDX_FACTOR_PRO_RAW_ASSET_KEY,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


@dg.asset(
    name=IDX_FACTOR_PRO_RAW_ASSET_KEY,
    partitions_def=cn_major_index_factor_trade_days,
    group_name="index",
    tags=build_asset_tags(
        layer=AssetLayer.RAW,
        data_domain=DataDomain.INDEX_TOPIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="idx_factor_pro",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_idx_factor_pro_approved_daily_major_indices",
        column_schema=RAW_TUSHARE_IDX_FACTOR_PRO_SCHEMA,
        path_template=lake_path_template(
            raw_idx_factor_pro_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api=IDX_FACTOR_PRO_API_NAME,
        source_category_path="指数专题",
        source_doc="docs/sources/tushare/指数专题/0358_指数技术因子(专业版).md",
        extra_metadata={
            "partition_set": cn_major_index_factor_trade_days.name,
            "source_scope": "date_effective_daily_major_index_seed",
            "write_boundary": "m2_raw_daily_asset",
        },
    ),
    description="Tushare 主要指数日级技术因子 Raw 数据。",
)
def raw_tushare_idx_factor_pro(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_idx_factor_pro_raw_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        tushare=tushare,
        partition_key=context.partition_key,
        run_id=context.run_id,
        request_policy=TushareRequestPolicy(),
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=IDX_FACTOR_PRO_SOURCE_COLUMNS,
            extra_metadata=result.to_details(),
        )
    )


__all__ = ["raw_tushare_idx_factor_pro"]
