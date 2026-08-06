"""Dagster Silver assets for native and derived major-index minute bars."""

import dagster as dg

from orchestrator.defs.assets.major_index_mins_raw import (
    RAW_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.io.major_index_mins_silver_writer import (
    write_major_index_mins_silver_partition,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_MAJOR_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


def _build_silver_asset(
    *,
    asset_name: str,
    frequency: str,
    dependency: dg.AssetsDefinition,
) -> dg.AssetsDefinition:
    source_frequency = (
        frequency
        if frequency not in {"90min", "120min"}
        else "30min" if frequency == "90min" else "60min"
    )

    @dg.asset(
        name=asset_name,
        deps=[dependency],
        partitions_def=cn_major_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(
            layer=AssetLayer.SILVER,
            data_domain=DataDomain.QUOTE_DATA,
        ),
        metadata=build_asset_definition_metadata(
            dataset_id="major_index_mins",
            source_system=SourceSystem.DERIVED,
            data_contract="standardized_major_index_minute_bars",
            column_schema=SILVER_MAJOR_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                silver_major_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    frequency,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata={
                "frequency": frequency,
                "source_frequency": source_frequency,
                "partition_set": cn_major_index_mins_trade_days.name,
                "derived_vwap_policy": "preserve_native_else_null",
                "write_boundary": "p4_dagster_asset",
            },
        ),
        description=f"主要指数 {frequency} Silver 分钟行情。",
    )
    def silver_asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        result = write_major_index_mins_silver_partition(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            freq=frequency,
            partition_key=context.partition_key,
            run_id=context.run_id,
        )
        return dg.MaterializeResult(
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.output_row_count,
                observed_columns=MAJOR_INDEX_MINS_SOURCE_COLUMNS,
                extra_metadata=result.to_details(),
            )
        )

    return silver_asset


_SILVER_ASSETS: list[dg.AssetsDefinition] = []
for index, (asset_name, frequency) in enumerate(
    zip(
        MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
        MAJOR_INDEX_MINS_SILVER_FREQS,
        strict=True,
    )
):
    if index < len(RAW_MAJOR_INDEX_MINS_ASSETS):
        dependency = RAW_MAJOR_INDEX_MINS_ASSETS[index]
    elif frequency == "90min":
        dependency = _SILVER_ASSETS[3]
    else:
        dependency = _SILVER_ASSETS[4]
    _SILVER_ASSETS.append(
        _build_silver_asset(
            asset_name=asset_name,
            frequency=frequency,
            dependency=dependency,
        )
    )

SILVER_MAJOR_INDEX_MINS_ASSETS = tuple(_SILVER_ASSETS)

(
    silver_major_index_mins_1m,
    silver_major_index_mins_5m,
    silver_major_index_mins_15m,
    silver_major_index_mins_30m,
    silver_major_index_mins_60m,
    silver_major_index_mins_90m,
    silver_major_index_mins_120m,
) = SILVER_MAJOR_INDEX_MINS_ASSETS

__all__ = [
    "SILVER_MAJOR_INDEX_MINS_ASSETS",
    "silver_major_index_mins_1m",
    "silver_major_index_mins_5m",
    "silver_major_index_mins_15m",
    "silver_major_index_mins_30m",
    "silver_major_index_mins_60m",
    "silver_major_index_mins_90m",
    "silver_major_index_mins_120m",
]
