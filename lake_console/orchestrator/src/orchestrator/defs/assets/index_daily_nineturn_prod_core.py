"""Publish validated major-index daily nine-turn Gold to prod serving."""

from pathlib import Path
from typing import Any

import dagster as dg
import duckdb

from orchestrator.defs.assets.major_index_nineturn import (
    gold_major_index_daily_nineturn,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.major_index_nineturn_integrity import (
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    gold_major_index_daily_nineturn_path,
    gold_market_major_indices_daily_path,
)
from orchestrator.defs.prod_db.index_daily_nineturn import (
    PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS,
    PROD_CORE_INDEX_DAILY_NINETURN_TABLE,
    replace_prod_core_index_daily_nineturn_partition,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresWriteResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    PROD_CORE_INDEX_DAILY_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_VERSION,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)

PROD_CORE_INDEX_DAILY_NINETURN_PATH_TEMPLATE = (
    "postgresql://prod/core_serving.index_nineturn_daily?trade_date={partition_key}"
)
_GOLD_COLUMNS = PROD_CORE_INDEX_DAILY_NINETURN_COLUMNS[:7]


@dg.asset(
    name="prod_core_index_daily_nineturn",
    deps=[gold_major_index_daily_nineturn],
    partitions_def=cn_a_index_trade_days,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.SERVING, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="major_index_daily_nineturn",
        source_system=SourceSystem.DERIVED,
        data_contract="core_serving.index_nineturn_daily",
        source_doc=(
            "wealth/docs/system/"
            "detail-page-nine-turn-integration-low-level-design-v1.md"
        ),
        path_template=PROD_CORE_INDEX_DAILY_NINETURN_PATH_TEMPLATE,
        column_schema=PROD_CORE_INDEX_DAILY_NINETURN_SCHEMA,
        extra_metadata={
            "target_system": "prod_postgres",
            "target_table": PROD_CORE_INDEX_DAILY_NINETURN_TABLE,
            "source_asset": "gold_major_index_daily_nineturn",
            "formula_version": MAJOR_INDEX_NINETURN_VERSION,
            "replace_contract": "transactional_delete_insert_read_back",
        },
    ),
    description="将主要指数日线九转 Gold 事务发布到独立 prod PostgreSQL serving。",
)
def prod_core_index_daily_nineturn(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    source_path = gold_major_index_daily_nineturn_path(lake_root.root(), partition_key)
    rows = load_gold_major_index_daily_nineturn_rows_for_prod_sync(
        duckdb_resource=duckdb,
        source_path=source_path,
        daily_source_path=gold_market_major_indices_daily_path(
            lake_root.root(), partition_key
        ),
        partition_key=partition_key,
    )
    with prod_postgres_write.connect() as connection:
        audit = replace_prod_core_index_daily_nineturn_partition(
            connection=connection,
            rows=rows,
            partition_key=partition_key,
        )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=PROD_CORE_INDEX_DAILY_NINETURN_PATH_TEMPLATE.format(
                partition_key=partition_key
            ),
            row_count=audit.row_count,
            observed_columns=audit.observed_columns,
            extra_metadata={
                "summary": "已同步主要指数日线九转到 prod PostgreSQL serving。",
                "result_status": "written",
                "partition_key": partition_key,
                "source_gold_path": str(source_path),
                "target_table": PROD_CORE_INDEX_DAILY_NINETURN_TABLE,
                "formula_version": MAJOR_INDEX_NINETURN_VERSION,
                "read_back_row_count": audit.read_back_row_count,
                "content_hash": audit.content_hash,
            },
        )
    )


def load_gold_major_index_daily_nineturn_rows_for_prod_sync(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
    daily_source_path: Path,
    partition_key: str,
) -> tuple[dict[str, Any], ...]:
    with duckdb_resource.connect() as connection:
        return load_gold_major_index_daily_nineturn_rows_with_connection(
            connection=connection,
            source_path=source_path,
            daily_source_path=daily_source_path,
            partition_key=partition_key,
        )


def load_gold_major_index_daily_nineturn_rows_with_connection(
    *,
    connection: duckdb.DuckDBPyConnection,
    source_path: Path,
    daily_source_path: Path,
    partition_key: str,
) -> tuple[dict[str, Any], ...]:
    diagnostics = audit_major_index_nineturn_integrity(
        connection,
        target_path=source_path,
        source_paths=(daily_source_path,),
        partition_key=partition_key,
        freq=None,
    )
    if not diagnostics.passed:
        raise RuntimeError(
            "Major-index daily nine-turn contract failed before prod sync: "
            f"{diagnostics.failed_rule_names}."
        )
    rows = connection.execute(
        f"""
        SELECT ts_code, trade_date, close, up_count, down_count,
               nine_up_turn, nine_down_turn
        FROM {read_parquet(source_path, hive_partitioning=False)}
        ORDER BY ts_code
        """
    ).fetchall()
    return tuple(dict(zip(_GOLD_COLUMNS, row, strict=True)) for row in rows)


__all__ = [
    "load_gold_major_index_daily_nineturn_rows_for_prod_sync",
    "load_gold_major_index_daily_nineturn_rows_with_connection",
    "prod_core_index_daily_nineturn",
]
