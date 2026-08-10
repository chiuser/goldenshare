"""Dagster Silver asset for standardized index technical factors."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.idx_factor_pro_raw import raw_tushare_idx_factor_pro
from orchestrator.defs.io.idx_factor_pro_silver_writer import (
    write_idx_factor_pro_silver_partition,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    silver_index_factor_pro_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_INDEX_FACTOR_PRO_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


@dg.asset(
    name=IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    deps=[raw_tushare_idx_factor_pro],
    partitions_def=cn_major_index_factor_trade_days,
    group_name="index",
    tags=build_asset_tags(
        layer=AssetLayer.SILVER,
        data_domain=DataDomain.INDEX_TOPIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="index_factor_pro",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_index_factor_pro",
        column_schema=SILVER_INDEX_FACTOR_PRO_SCHEMA,
        path_template=lake_path_template(
            silver_index_factor_pro_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "partition_set": cn_major_index_factor_trade_days.name,
            "source_asset_key": raw_tushare_idx_factor_pro.key.to_user_string(),
            "write_boundary": "silver_daily_partition",
        },
    ),
    description="主要指数日级技术因子标准化 Silver 数据。",
)
def silver_index_factor_pro(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_idx_factor_pro_silver_partition(
        lake_root_path=lake_root.root(),
        staging_root_path=Path(DEFAULT_LAKE_STAGING_ROOT),
        duckdb_resource=duckdb,
        partition_key=context.partition_key,
        run_id=context.run_id,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=IDX_FACTOR_PRO_SOURCE_COLUMNS,
            extra_metadata=result.to_details(),
        )
    )


__all__ = ["silver_index_factor_pro"]
