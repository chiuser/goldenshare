"""Dagster Silver assets for native and derived index minute frequencies."""

import dagster as dg

from orchestrator.defs.assets.index_mins_silver import (
    INDEX_MINS_SILVER_COLUMNS,
    write_silver_index_mins_partition,
)
from orchestrator.defs.assets.index_mins_raw import (
    raw_index_mins_1m,
    raw_index_mins_5m,
    raw_index_mins_15m,
    raw_index_mins_30m,
    raw_index_mins_60m,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    silver_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import SILVER_INDEX_MINS_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import AssetLayer, DataDomain, build_asset_tags
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


_NATIVE_ASSETS = {
    1: raw_index_mins_1m,
    5: raw_index_mins_5m,
    15: raw_index_mins_15m,
    30: raw_index_mins_30m,
    60: raw_index_mins_60m,
}


def _silver_asset_metadata(freq: int) -> dict[str, object]:
    return {
        "frequency": f"{freq}min",
        "source_frequency": f"{freq}min" if freq < 90 else ("30min" if freq == 90 else "60min"),
        "derived_vwap_policy": "preserve_native_vwap_else_null",
        "write_boundary": "p4_dagster_asset",
    }


def _build_silver_asset(*, asset_name: str, freq: int, deps: list[object]) -> dg.AssetsDefinition:
    @dg.asset(
        name=asset_name,
        deps=deps,
        partitions_def=cn_a_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
        metadata=build_asset_definition_metadata(
            dataset_id="index_mins",
            source_system=SourceSystem.DERIVED,
            data_contract="standardized_index_minute_bars",
            column_schema=SILVER_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                silver_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    f"{freq}min",
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata=_silver_asset_metadata(freq),
        ),
        description=f"指数 {freq} 分钟 Silver 行情，原生标准化或按固定窗口派生。",
    )
    def silver_asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        result = write_silver_index_mins_partition(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            freq=freq,
            partition_key=context.partition_key,
        )
        return dg.MaterializeResult(
            metadata=build_materialization_metadata(
                uri=result.silver_file_path,
                row_count=result.written_row_count,
                observed_columns=INDEX_MINS_SILVER_COLUMNS,
                extra_metadata=result.to_metadata(),
            )
        )

    return silver_asset


silver_index_mins_1m = _build_silver_asset(
    asset_name="silver_index_mins_1m", freq=1, deps=[raw_index_mins_1m]
)
silver_index_mins_5m = _build_silver_asset(
    asset_name="silver_index_mins_5m", freq=5, deps=[raw_index_mins_5m]
)
silver_index_mins_15m = _build_silver_asset(
    asset_name="silver_index_mins_15m", freq=15, deps=[raw_index_mins_15m]
)
silver_index_mins_30m = _build_silver_asset(
    asset_name="silver_index_mins_30m", freq=30, deps=[raw_index_mins_30m]
)
silver_index_mins_60m = _build_silver_asset(
    asset_name="silver_index_mins_60m", freq=60, deps=[raw_index_mins_60m]
)
silver_index_mins_90m = _build_silver_asset(
    asset_name="silver_index_mins_90m", freq=90, deps=[silver_index_mins_30m]
)
silver_index_mins_120m = _build_silver_asset(
    asset_name="silver_index_mins_120m", freq=120, deps=[silver_index_mins_60m]
)

SILVER_INDEX_MINS_ASSETS = (
    silver_index_mins_1m,
    silver_index_mins_5m,
    silver_index_mins_15m,
    silver_index_mins_30m,
    silver_index_mins_60m,
    silver_index_mins_90m,
    silver_index_mins_120m,
)

__all__ = [
    "SILVER_INDEX_MINS_ASSETS",
    "silver_index_mins_1m",
    "silver_index_mins_5m",
    "silver_index_mins_15m",
    "silver_index_mins_30m",
    "silver_index_mins_60m",
    "silver_index_mins_90m",
    "silver_index_mins_120m",
]
