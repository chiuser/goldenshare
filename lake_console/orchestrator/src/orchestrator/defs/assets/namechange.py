import os
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.duckdb_sql import (
    NAMECHANGE_RAW_COLUMNS,
    NAMECHANGE_SILVER_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.namechange_timeline import (
    NAMECHANGE_TIMELINE_RULE_VERSION,
    build_latest_announcement_namechange_timeline,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    raw_namechange_path,
    silver_namechange_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_NAMECHANGE_SCHEMA,
    SILVER_NAMECHANGE_SCHEMA,
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
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_distinct_to_raw


NAMECHANGE_API_PARAMS: dict[str, object] = {}
NAMECHANGE_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_NAMECHANGE_SCHEMA
}
NAMECHANGE_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_NAMECHANGE_SCHEMA
}


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _read_raw_rows(connection, path: Path) -> list[dict[str, Any]]:
    columns = tuple(NAMECHANGE_RAW_COLUMNS)
    select_columns = ", ".join(columns)
    rows = connection.execute(
        f"""
        SELECT {select_columns}
        FROM {read_parquet(path, hive_partitioning=False)}
        """
    ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _read_current_listed_stock_codes(connection, path: Path) -> set[str]:
    rows = connection.execute(
        f"""
        SELECT ts_code
        FROM {read_parquet(path, hive_partitioning=False)}
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _replace_silver_rows(
    *,
    duckdb: DuckDBResource,
    rows: tuple[dict[str, Any], ...],
    target_path: Path,
) -> tuple[int, tuple[str, ...]]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    fields = tuple(NAMECHANGE_SILVER_REQUIRED_COLUMNS)
    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f"{field} {NAMECHANGE_SILVER_COLUMN_TYPES[field]}" for field in fields
        )
        connection.execute(f"CREATE TEMP TABLE silver_rows ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            values = [[row.get(field) for field in fields] for row in rows]
            connection.executemany(
                f"INSERT INTO silver_rows VALUES ({placeholders})", values
            )

        select_sql = ", ".join(
            f"CAST({field} AS {NAMECHANGE_SILVER_COLUMN_TYPES[field]}) AS {field}"
            for field in fields
        )
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {select_sql} FROM silver_rows ORDER BY ts_code, start_date",
                temporary_path,
            )
        )
        row_count = _row_count(connection, temporary_path, hive_partitioning=False)
        columns = tuple(
            _column_names(connection, temporary_path, hive_partitioning=False)
        )

    os.replace(temporary_path, target_path)
    return row_count, columns


@dg.asset(
    name="raw_tushare_namechange",
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="namechange",
        source_system=SourceSystem.TUSHARE,
        source_api="namechange",
        source_category_path="股票数据 / 基础数据",
        source_doc="docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md",
        data_contract="source_mirror_deduplicated_full_snapshot",
        column_schema=RAW_TUSHARE_NAMECHANGE_SCHEMA,
        path_template=lake_path_template(
            raw_namechange_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare namechange full snapshot; date fields remain YYYYMMDD "
                "strings and exact full-row duplicates are removed before writing."
            ),
            "update_policy": "daily_full_snapshot_api_replace",
        },
    ),
    description="Tushare 股票曾用名原始全量快照，按全字段完全一致去重。",
)
def raw_tushare_namechange(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    target_path = raw_namechange_path(lake_root.root())
    metadata = fetch_tushare_full_file_distinct_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="namechange",
        api_params=NAMECHANGE_API_PARAMS,
        fields=NAMECHANGE_RAW_COLUMNS,
        column_types=NAMECHANGE_RAW_COLUMN_TYPES,
        target_path=target_path,
        allow_empty=False,
    )
    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_namechange",
    deps=[raw_tushare_namechange, silver_stock_basic],
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="namechange",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_namechange_event_timeline_full_snapshot",
        column_schema=SILVER_NAMECHANGE_SCHEMA,
        path_template=lake_path_template(
            silver_namechange_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "canonicalization_rule_version": NAMECHANGE_TIMELINE_RULE_VERSION,
            "timeline_policy": (
                "Choose the latest announcement for each ts_code/start_date, close "
                "overlapping intervals by next start date, and preserve source gaps."
            ),
        },
    ),
    description="股票曾用名标准时间线，确保同一股票同一天最多命中一个名称区间。",
)
def silver_namechange(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_namechange_path(lake_root.root())
    stock_basic_path = silver_stock_basic_path(lake_root.root())
    target_path = silver_namechange_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw namechange file: {raw_path}")
    if not stock_basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {stock_basic_path}")

    with duckdb.connect() as connection:
        raw_rows = _read_raw_rows(connection, raw_path)
        current_listed_stock_codes = _read_current_listed_stock_codes(
            connection, stock_basic_path
        )

    filtered_rows = [
        row for row in raw_rows if str(row.get("ts_code")) in current_listed_stock_codes
    ]

    timeline = build_latest_announcement_namechange_timeline(filtered_rows)
    if timeline.blocking_conflict_count:
        raise RuntimeError(
            "Namechange timeline canonicalization failed: "
            f"unresolved={timeline.unresolved_conflict_count}, "
            f"invalid_date_order={timeline.invalid_date_order_count}, "
            f"overlap={timeline.overlap_count}, "
            f"multi_open={timeline.multi_open_code_count}."
        )
    if not timeline.rows:
        raise RuntimeError("Namechange timeline produced 0 silver rows.")

    row_count, columns = _replace_silver_rows(
        duckdb=duckdb,
        rows=timeline.rows,
        target_path=target_path,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "raw_file_path": str(raw_path),
                "stock_basic_file_path": str(stock_basic_path),
                "source_row_count": timeline.source_row_count,
                "raw_source_row_count": len(raw_rows),
                "current_listed_stock_count": len(current_listed_stock_codes),
                "filtered_delisted_row_count": len(raw_rows) - len(filtered_rows),
                "selected_event_count": timeline.selected_event_count,
                "duplicate_removed_count": 0,
                "merged_same_name_count": timeline.merged_same_name_count,
                "same_name_same_end_reason_resolved_count": (
                    timeline.same_name_same_end_reason_resolved_count
                ),
                "same_name_diff_end_resolved_count": (
                    timeline.same_name_diff_end_resolved_count
                ),
                "open_interval_count": sum(
                    1 for row in timeline.rows if row.get("end_date") is None
                ),
                "canonicalization_rule_version": NAMECHANGE_TIMELINE_RULE_VERSION,
                "unresolved_interval_conflict_count": (
                    timeline.unresolved_conflict_count
                ),
                "invalid_date_order_count": timeline.invalid_date_order_count,
                "overlap_count": timeline.overlap_count,
                "multi_open_code_count": timeline.multi_open_code_count,
                "adjacent_gap_count": timeline.adjacent_gap_count,
                "known_adjacent_gap_count": timeline.known_adjacent_gap_count,
                "unknown_adjacent_gap_count": timeline.unknown_adjacent_gap_count,
                "adjacent_gap_sample": list(timeline.adjacent_gap_samples),
                "unknown_adjacent_gap_sample": list(
                    timeline.unknown_adjacent_gap_samples
                ),
            },
        )
    )
