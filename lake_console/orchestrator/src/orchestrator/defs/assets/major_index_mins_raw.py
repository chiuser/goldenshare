"""Dagster Raw assets for Tushare major-index minute bars."""

import dagster as dg

from orchestrator.defs.io.major_index_mins_raw_writer import (
    write_major_index_mins_raw_partition,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_MAJOR_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


def _build_raw_asset(*, asset_name: str, source_freq: str) -> dg.AssetsDefinition:
    @dg.asset(
        name=asset_name,
        partitions_def=cn_major_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(
            layer=AssetLayer.RAW,
            data_domain=DataDomain.QUOTE_DATA,
        ),
        metadata=build_asset_definition_metadata(
            dataset_id="major_index_mins",
            source_system=SourceSystem.TUSHARE,
            data_contract="tushare_major_index_mins_exact_session",
            column_schema=RAW_MAJOR_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                raw_major_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    source_freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            source_api="idx_mins",
            source_category_path="指数专题",
            source_doc="docs/sources/tushare/指数专题/0419_股票历史分钟行情.md",
            extra_metadata={
                "frequency": source_freq,
                "partition_set": cn_major_index_mins_trade_days.name,
                "source_scope": "versioned_major_index_code_lifecycle",
                "write_boundary": "p4_dagster_asset",
            },
        ),
        description=f"Tushare 主要指数 {source_freq} Raw 分钟行情。",
    )
    def raw_asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
        tushare: TushareResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        result = write_major_index_mins_raw_partition(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            tushare=tushare,
            source_freq=source_freq,
            partition_key=context.partition_key,
            run_id=context.run_id,
            request_policy=TushareRequestPolicy(),
        )
        return dg.MaterializeResult(
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.output_row_count,
                observed_columns=MAJOR_INDEX_MINS_SOURCE_COLUMNS,
                extra_metadata=result.to_details(),
            )
        )

    return raw_asset


RAW_MAJOR_INDEX_MINS_ASSETS = tuple(
    _build_raw_asset(asset_name=asset_name, source_freq=source_freq)
    for asset_name, source_freq in zip(
        MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
        MAJOR_INDEX_MINS_SOURCE_FREQS,
        strict=True,
    )
)

(
    raw_major_index_mins_1m,
    raw_major_index_mins_5m,
    raw_major_index_mins_15m,
    raw_major_index_mins_30m,
    raw_major_index_mins_60m,
) = RAW_MAJOR_INDEX_MINS_ASSETS

__all__ = [
    "RAW_MAJOR_INDEX_MINS_ASSETS",
    "raw_major_index_mins_1m",
    "raw_major_index_mins_5m",
    "raw_major_index_mins_15m",
    "raw_major_index_mins_30m",
    "raw_major_index_mins_60m",
]
