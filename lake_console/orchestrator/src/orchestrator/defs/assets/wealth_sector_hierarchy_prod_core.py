"""Publish the approved Eastmoney industry hierarchy to prod PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.dc_industry_hierarchy import (
    silver_dc_industry_hierarchy,
)
from orchestrator.defs.duckdb_sql import describe_parquet_query, read_parquet
from orchestrator.defs.paths import silver_dc_industry_hierarchy_path
from orchestrator.defs.prod_db.wealth_sector_hierarchy import (
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS,
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
    WealthSectorHierarchyContentAudit,
    audit_wealth_sector_hierarchy_rows,
    replace_prod_core_wealth_sector_hierarchy,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresWriteResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    PROD_CORE_WEALTH_SECTOR_HIERARCHY_SCHEMA,
    SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
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
from orchestrator.utils.dg_log_helper import DgStdoutLogger

PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE = (
    "postgresql://prod/core_serving.wealth_sector_hierarchy"
)
_SOURCE_COLUMNS = tuple(
    column.name for column in SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA
)
_SOURCE_COLUMN_TYPES = tuple(
    column.type for column in SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA
)
_LOGGER = DgStdoutLogger("wealth_sector_hierarchy")


@dataclass(frozen=True, slots=True)
class WealthSectorHierarchySourceSnapshot:
    source_path: Path
    content: WealthSectorHierarchyContentAudit


def load_silver_wealth_sector_hierarchy_for_prod_sync(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
) -> WealthSectorHierarchySourceSnapshot:
    """Read one fixed Silver file and enforce the full publication contract."""

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Missing Silver wealth sector hierarchy snapshot: {source_path}"
        )

    with duckdb_resource.connect() as connection:
        observed_schema = connection.execute(
            describe_parquet_query(source_path, hive_partitioning=False)
        ).fetchall()
        observed_columns = tuple(str(row[0]) for row in observed_schema)
        observed_types = tuple(str(row[1]) for row in observed_schema)
        if observed_columns != _SOURCE_COLUMNS or observed_types != _SOURCE_COLUMN_TYPES:
            raise RuntimeError(
                "Silver wealth sector hierarchy schema contract failed: "
                f"observed_columns={observed_columns}, "
                f"observed_types={observed_types}."
            )

        relation = read_parquet(source_path, hive_partitioning=False)
        source_rows = connection.execute(
            f"""
            SELECT
              ts_code AS sector_code,
              name AS sector_name,
              industry_level,
              industry_level_name,
              parent_ts_code AS parent_sector_code,
              parent_name AS parent_sector_name,
              root_ts_code AS root_sector_code,
              root_name AS root_sector_name,
              hierarchy_path,
              is_leaf,
              display_order,
              baseline_version,
              source_received_date,
              code_reference_trade_date
            FROM {relation}
            ORDER BY display_order, ts_code
            """
        ).fetchall()

    mapped_rows = tuple(
        dict(
            zip(
                PROD_CORE_WEALTH_SECTOR_HIERARCHY_CONTENT_COLUMNS,
                row,
                strict=True,
            )
        )
        for row in source_rows
    )
    return WealthSectorHierarchySourceSnapshot(
        source_path=source_path,
        content=audit_wealth_sector_hierarchy_rows(mapped_rows),
    )


@dg.asset(
    name="prod_core_wealth_sector_hierarchy",
    deps=[silver_dc_industry_hierarchy],
    group_name="wealth",
    tags=build_asset_tags(
        layer=AssetLayer.SERVING,
        data_domain=DataDomain.BASIC_DATA,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_industry_hierarchy",
        source_system=SourceSystem.SEED,
        data_contract=PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
        source_doc=(
            "wealth/docs/pages/market-overview/"
            "sector-overview-low-level-design-v2.md"
        ),
        path_template=PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE,
        column_schema=PROD_CORE_WEALTH_SECTOR_HIERARCHY_SCHEMA,
        extra_metadata={
            "source_asset": "silver_dc_industry_hierarchy",
            "target_system": "prod_postgres",
            "target_table": PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
            "replace_contract": "transactional_delete_insert_read_back",
        },
    ),
    description=(
        "将已验收的东方财富三级行业层级 Silver 全量快照发布到 prod PostgreSQL，"
        "供财富首页板块速览读取。"
    ),
)
def prod_core_wealth_sector_hierarchy(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    source_path = silver_dc_industry_hierarchy_path(lake_root.root())
    _LOGGER.stdout(
        "prod_core_wealth_sector_hierarchy_started",
        source_path=str(source_path),
        target_table=PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
    )

    source_snapshot = load_silver_wealth_sector_hierarchy_for_prod_sync(
        duckdb_resource=duckdb,
        source_path=source_path,
    )
    with prod_postgres_write.connect() as connection:
        sync_audit = replace_prod_core_wealth_sector_hierarchy(
            connection=connection,
            rows=source_snapshot.content.rows,
        )

    _LOGGER.stdout(
        "prod_core_wealth_sector_hierarchy_completed",
        source_row_count=source_snapshot.content.row_count,
        output_row_count=sync_audit.row_count,
        read_back_row_count=sync_audit.read_back_row_count,
        target_table=PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE,
            row_count=sync_audit.row_count,
            observed_columns=PROD_CORE_WEALTH_SECTOR_HIERARCHY_COLUMNS,
            extra_metadata={
                "summary": "已将东方财富三级行业层级发布到 prod PostgreSQL。",
                "next_action": "核对 496 行、31/128/337 分布和 source/read-back hash。",
                "result_status": "written",
                "diagnostic_ref": (
                    "完整诊断看 prod_core_wealth_sector_hierarchy materialization "
                    "metadata 和 run stdout。"
                ),
                "source_asset": "silver_dc_industry_hierarchy",
                "source_silver_path": str(source_path),
                "prod_table": PROD_CORE_WEALTH_SECTOR_HIERARCHY_TABLE,
                "replace_mode": "transactional_delete_then_insert",
                "source_row_count": source_snapshot.content.row_count,
                "read_back_row_count": sync_audit.read_back_row_count,
                "level_count_distribution": dict(sync_audit.level_counts),
                "baseline_version": sync_audit.baseline_version,
                "code_reference_trade_date": (
                    source_snapshot.content.code_reference_trade_date.isoformat()
                ),
                "source_hash": source_snapshot.content.content_hash,
                "prod_read_back_hash": sync_audit.read_back_content_hash,
                "published_at": sync_audit.published_at.isoformat(),
            },
        )
    )


__all__ = [
    "PROD_CORE_WEALTH_SECTOR_HIERARCHY_PATH_TEMPLATE",
    "WealthSectorHierarchySourceSnapshot",
    "load_silver_wealth_sector_hierarchy_for_prod_sync",
    "prod_core_wealth_sector_hierarchy",
]
