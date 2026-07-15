"""Dagster asset wrapper for the ``dc_daily_technical`` Gold writer."""

import dagster as dg

from orchestrator.defs.assets.dc_daily_technical import (
    write_gold_dc_daily_technical_partition,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_dc_daily_technical_path,
    lake_path_template,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


@dg.asset(
    name="gold_dc_daily_technical",
    deps=["silver_dc_daily"],
    partitions_def=cn_a_index_trade_days,
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.DERIVED_METRIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_daily_technical",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_dc_daily_technical",
        column_schema=GOLD_DC_DAILY_TECHNICAL_SCHEMA,
        path_template=lake_path_template(
            gold_dc_daily_technical_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "partition_set": cn_a_index_trade_days.name,
            "source_asset": "silver_dc_daily",
            "write_boundary": "p3_duckdb_set_based_staging_atomic_replace",
            "formula_contract": (
                "MA=5/10/15/20/30/60/120/250; MACD=12/26/9; "
                "KDJ=9/3/3; BOLL=20/2; stddev_pop; warmup=NULL."
            ),
        },
    ),
    description=(
        "从 silver_dc_daily 生成板块 MA、KDJ、MACD、BOLL Gold 指标；"
        "预热期指标保持 NULL。"
    ),
)
def gold_dc_daily_technical(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_gold_dc_daily_technical_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        partition_key=context.partition_key,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=tuple(column.name for column in GOLD_DC_DAILY_TECHNICAL_SCHEMA),
            extra_metadata=result.to_metadata(),
        )
    )


__all__ = ["gold_dc_daily_technical"]
