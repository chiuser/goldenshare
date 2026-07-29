"""Dagster Raw assets for the Prod-backed index minute data set."""

import dagster as dg

from orchestrator.defs.assets.index_basic import silver_index_basic
from orchestrator.defs.assets.index_mins import (
    INDEX_MINS_RAW_COLUMNS,
    write_raw_index_mins_partition_from_prod_db,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_index_mins_path,
)
from orchestrator.defs.prod_db.index_mins import load_prod_index_mins_active_pool
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, ProdPostgresResource
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_MINS_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import AssetLayer, DataDomain, build_asset_tags
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_SOURCE_FREQS
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


def _raw_asset_metadata(source_freq: str) -> dict[str, object]:
    return {
        "frequency": source_freq,
        "source_method": "prod_db_readonly_range_stream",
        "active_pool_contract": "ops.index_series_active(resource='index_mins')",
        "write_boundary": "p4_dagster_asset",
    }


def _build_raw_asset(*, asset_name: str, source_freq: str) -> dg.AssetsDefinition:
    @dg.asset(
        name=asset_name,
        deps=[silver_index_basic],
        partitions_def=cn_a_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
        metadata=build_asset_definition_metadata(
            dataset_id="index_mins",
            source_system=SourceSystem.PROD_CORE_DB,
            data_contract="prod_core_index_mins_by_frequency_trade_date",
            column_schema=RAW_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                raw_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    source_freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            source_doc="docs/sources/tushare/指数专题/0419_股票历史分钟行情.md",
            extra_metadata=_raw_asset_metadata(source_freq),
        ),
        description=f"从 Prod DB 只读同步指数 {source_freq} 分钟 Raw 行情。",
    )
    def raw_asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
        prod_postgres: ProdPostgresResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        active_pool = load_prod_index_mins_active_pool(prod_postgres=prod_postgres)
        result = write_raw_index_mins_partition_from_prod_db(
            lake_root=lake_root.root(),
            duckdb=duckdb,
            prod_postgres=prod_postgres,
            source_freq=source_freq,
            partition_key=context.partition_key,
            active_pool=active_pool,
        )
        return dg.MaterializeResult(
            metadata=build_materialization_metadata(
                uri=result.raw_file_path,
                row_count=result.written_row_count,
                observed_columns=INDEX_MINS_RAW_COLUMNS,
                extra_metadata=result.to_metadata(),
            )
        )

    return raw_asset


raw_index_mins_1m = _build_raw_asset(
    asset_name="raw_index_mins_1m", source_freq=INDEX_MINS_SOURCE_FREQS[0]
)
raw_index_mins_5m = _build_raw_asset(
    asset_name="raw_index_mins_5m", source_freq=INDEX_MINS_SOURCE_FREQS[1]
)
raw_index_mins_15m = _build_raw_asset(
    asset_name="raw_index_mins_15m", source_freq=INDEX_MINS_SOURCE_FREQS[2]
)
raw_index_mins_30m = _build_raw_asset(
    asset_name="raw_index_mins_30m", source_freq=INDEX_MINS_SOURCE_FREQS[3]
)
raw_index_mins_60m = _build_raw_asset(
    asset_name="raw_index_mins_60m", source_freq=INDEX_MINS_SOURCE_FREQS[4]
)

RAW_INDEX_MINS_ASSETS = (
    raw_index_mins_1m,
    raw_index_mins_5m,
    raw_index_mins_15m,
    raw_index_mins_30m,
    raw_index_mins_60m,
)

__all__ = [
    "RAW_INDEX_MINS_ASSETS",
    "raw_index_mins_1m",
    "raw_index_mins_5m",
    "raw_index_mins_15m",
    "raw_index_mins_30m",
    "raw_index_mins_60m",
]
