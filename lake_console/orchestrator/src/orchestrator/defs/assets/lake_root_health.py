import dagster as dg

from orchestrator.defs.duckdb_connection import DEFAULT_DUCKDB_TEMP_DIRECTORY
from orchestrator.defs.health.lake_root import evaluate_lake_root_health
from orchestrator.defs.resources import LakeRootResource
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
    name="lake_root_health",
    group_name="platform_observability",
    tags=build_asset_tags(
        layer=AssetLayer.PLATFORM,
        data_domain=DataDomain.PLATFORM_OBSERVABILITY,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="lake_root_health",
        source_system=SourceSystem.DERIVED,
        data_contract="lake_root_health_v1",
        extra_metadata={
            "health_asset_type": "infrastructure",
            "writes_parquet": False,
        },
    ),
    description=(
        "平台健康检查：确认 lake root 必要目录、读写 canary、磁盘空间和 "
        "DuckDB temp 可用，不产生 Parquet 业务数据。"
    ),
)
def lake_root_health(lake_root: LakeRootResource) -> dg.MaterializeResult:
    status = evaluate_lake_root_health(
        lake_root=lake_root.root(),
        duckdb_temp_directory=DEFAULT_DUCKDB_TEMP_DIRECTORY,
    )
    metadata = status.metadata()
    if not status.healthy:
        raise dg.Failure(
            description="Lake root 平台健康检查失败。",
            metadata=metadata,
        )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(extra_metadata=metadata)
    )
