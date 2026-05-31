import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.assets.namechange import silver_namechange
from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    silver_namechange_path,
    silver_stock_basic_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
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
from orchestrator.seeds.basic.stock_identity_mappings import (
    STOCK_IDENTITY_ALLOWED_CONFIDENCE as STOCK_IDENTITY_ALLOWED_SEED_CONFIDENCE,
    STOCK_IDENTITY_ALLOWED_SEED_SOURCES,
    STOCK_IDENTITY_MAPPINGS_SEED_PATH,
    STOCK_IDENTITY_MAPPINGS_SEED_VERSION,
    StockIdentityMappingSeedRow,
    load_stock_identity_mapping_seed,
)


STOCK_BASIC_IDENTITY_SOURCE = "stock_basic"
STOCK_BASIC_IDENTITY_CONFIDENCE = "confirmed"
STOCK_IDENTITY_MAP_TIMEZONE = ZoneInfo("Asia/Shanghai")
STOCK_IDENTITY_ALLOWED_SOURCES = frozenset(
    {STOCK_BASIC_IDENTITY_SOURCE, *STOCK_IDENTITY_ALLOWED_SEED_SOURCES}
)
STOCK_IDENTITY_ALLOWED_CONFIDENCE = STOCK_IDENTITY_ALLOWED_SEED_CONFIDENCE
STOCK_IDENTITY_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA
}


@dataclass(frozen=True)
class StockIdentityMapBuildResult:
    rows: tuple[dict[str, Any], ...]
    stock_basic_row_count: int
    seed_row_count: int
    source_distribution: tuple[dict[str, Any], ...]
    confidence_distribution: tuple[dict[str, Any], ...]


def build_stock_identity_map_rows(
    *,
    stock_basic_rows: Sequence[dict[str, Any]],
    seed_rows: Sequence[StockIdentityMappingSeedRow],
    namechange_codes: set[str],
    created_at: datetime,
) -> StockIdentityMapBuildResult:
    """Build the full stock identity map snapshot from current listed facts and seed."""

    stock_basic_by_code = {
        str(row["ts_code"]): row
        for row in stock_basic_rows
        if row.get("ts_code") is not None and str(row.get("ts_code")).strip()
    }
    if not stock_basic_by_code:
        raise RuntimeError("silver_stock_basic produced no current listed stock rows.")

    rows: list[dict[str, Any]] = [
        _self_mapping_row(stock_basic_row, created_at)
        for stock_basic_row in stock_basic_by_code.values()
    ]

    missing_latest_codes = sorted(
        {
            seed_row.latest_ts_code
            for seed_row in seed_rows
            if seed_row.latest_ts_code not in stock_basic_by_code
        }
    )
    if missing_latest_codes:
        raise RuntimeError(
            "Stock identity mapping seed latest_ts_code not found in silver_stock_basic: "
            f"{missing_latest_codes[:20]}"
        )

    missing_namechange_latest_codes = sorted(
        {
            seed_row.latest_ts_code
            for seed_row in seed_rows
            if seed_row.identity_source == "namechange"
            and seed_row.latest_ts_code not in namechange_codes
        }
    )
    if missing_namechange_latest_codes:
        raise RuntimeError(
            "Namechange inferred identity seed latest_ts_code not found in "
            f"silver_namechange: {missing_namechange_latest_codes[:20]}"
        )

    for seed_row in seed_rows:
        latest_stock_basic = stock_basic_by_code[seed_row.latest_ts_code]
        rows.append(
            {
                "latest_ts_code": seed_row.latest_ts_code,
                "source_ts_code": seed_row.source_ts_code,
                "valid_from": seed_row.valid_from,
                "valid_to": seed_row.valid_to,
                "effective_list_date": latest_stock_basic["list_date"],
                "effective_delist_date": latest_stock_basic["delist_date"],
                "identity_source": seed_row.identity_source,
                "confidence": seed_row.confidence,
                "reason": seed_row.reason,
                "created_at": created_at,
            }
        )

    _validate_identity_rows(rows)
    sorted_rows = tuple(
        sorted(
            rows,
            key=lambda row: (str(row["latest_ts_code"]), str(row["source_ts_code"])),
        )
    )
    return StockIdentityMapBuildResult(
        rows=sorted_rows,
        stock_basic_row_count=len(stock_basic_by_code),
        seed_row_count=len(seed_rows),
        source_distribution=_distribution(sorted_rows, "identity_source"),
        confidence_distribution=_distribution(sorted_rows, "confidence"),
    )


def write_stock_identity_map_snapshot(
    *,
    duckdb: DuckDBResource,
    rows: Sequence[dict[str, Any]],
    target_path: Path,
) -> tuple[int, tuple[str, ...]]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    fields = tuple(SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS)
    with duckdb.connect() as connection:
        column_defs = ", ".join(
            f"{field} {STOCK_IDENTITY_COLUMN_TYPES[field]}" for field in fields
        )
        connection.execute(f"CREATE TEMP TABLE identity_rows ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _ in fields)
            values = [[row.get(field) for field in fields] for row in rows]
            connection.executemany(
                f"INSERT INTO identity_rows VALUES ({placeholders})",
                values,
            )

        select_sql = ", ".join(
            f"CAST({field} AS {STOCK_IDENTITY_COLUMN_TYPES[field]}) AS {field}"
            for field in fields
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT "
                f"{select_sql} "
                "FROM identity_rows "
                "ORDER BY latest_ts_code, source_ts_code",
                temporary_path,
            )
        )
        row_count = int(
            connection.execute(
                count_parquet_query(temporary_path, hive_partitioning=False)
            ).fetchone()[0]
        )
        columns = tuple(
            row[0]
            for row in connection.execute(
                describe_parquet_query(temporary_path, hive_partitioning=False)
            ).fetchall()
        )

    os.replace(temporary_path, target_path)
    return row_count, columns


def _self_mapping_row(
    stock_basic_row: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    ts_code = str(stock_basic_row["ts_code"])
    return {
        "latest_ts_code": ts_code,
        "source_ts_code": ts_code,
        "valid_from": stock_basic_row["list_date"],
        "valid_to": stock_basic_row["delist_date"],
        "effective_list_date": stock_basic_row["list_date"],
        "effective_delist_date": stock_basic_row["delist_date"],
        "identity_source": STOCK_BASIC_IDENTITY_SOURCE,
        "confidence": STOCK_BASIC_IDENTITY_CONFIDENCE,
        "reason": "current listed stock self mapping",
        "created_at": created_at,
    }


def _validate_identity_rows(rows: Sequence[dict[str, Any]]) -> None:
    source_counts = Counter(str(row["source_ts_code"]) for row in rows)
    duplicate_source_codes = sorted(
        source_code for source_code, count in source_counts.items() if count > 1
    )
    if duplicate_source_codes:
        raise RuntimeError(
            "stock identity map source_ts_code must be unique: "
            f"{duplicate_source_codes[:20]}"
        )

    missing_latest_codes = [
        row
        for row in rows
        if row.get("latest_ts_code") is None
        or not str(row["latest_ts_code"]).strip()
    ]
    missing_source_codes = [
        row
        for row in rows
        if row.get("source_ts_code") is None
        or not str(row["source_ts_code"]).strip()
    ]
    if missing_latest_codes or missing_source_codes:
        raise RuntimeError("stock identity map contains blank latest_ts_code/source_ts_code.")

    unsupported_sources = sorted(
        {str(row["identity_source"]) for row in rows}
        - set(STOCK_IDENTITY_ALLOWED_SOURCES)
    )
    if unsupported_sources:
        raise RuntimeError(f"Unsupported identity_source values: {unsupported_sources}")

    unsupported_confidence = sorted(
        {str(row["confidence"]) for row in rows}
        - set(STOCK_IDENTITY_ALLOWED_CONFIDENCE)
    )
    if unsupported_confidence:
        raise RuntimeError(f"Unsupported confidence values: {unsupported_confidence}")

    invalid_date_rows = [
        row
        for row in rows
        if row.get("valid_to") is not None and row["valid_to"] < row["valid_from"]
    ]
    if invalid_date_rows:
        raise RuntimeError(
            "stock identity map contains valid_to before valid_from: "
            f"{_sample_rows(invalid_date_rows)}"
        )


def _distribution(
    rows: Sequence[dict[str, Any]],
    field: str,
) -> tuple[dict[str, Any], ...]:
    counts = Counter(str(row[field]) for row in rows)
    return tuple(
        {"value": value, "row_count": count}
        for value, count in sorted(counts.items())
    )


def _sample_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows[:10]:
        sample = {}
        for key, value in row.items():
            sample[key] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _read_stock_basic_rows(
    duckdb: DuckDBResource,
    path: Path,
) -> tuple[dict[str, Any], ...]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT ts_code, list_date, delist_date
            FROM {read_parquet(path, hive_partitioning=False)}
            """
        ).fetchall()
    return tuple(
        {
            "ts_code": row[0],
            "list_date": row[1],
            "delist_date": row[2],
        }
        for row in rows
    )


def _read_namechange_codes(
    duckdb: DuckDBResource,
    path: Path,
) -> set[str]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT ts_code
            FROM {read_parquet(path, hive_partitioning=False)}
            """
        ).fetchall()
    return {str(row[0]) for row in rows}


@dg.asset(
    name="silver_stock_identity_map",
    deps=[silver_stock_basic, silver_namechange],
    group_name="basic",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_identity_map",
        source_system=SourceSystem.DERIVED,
        data_contract="current_listed_stock_identity_full_snapshot",
        column_schema=SILVER_STOCK_IDENTITY_MAP_SCHEMA,
        path_template=lake_path_template(
            silver_stock_identity_map_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "generation_policy": (
                "Full snapshot rebuilt from silver_stock_basic self mappings and "
                "version-controlled non-self identity seed mappings."
            ),
            "seed_version": STOCK_IDENTITY_MAPPINGS_SEED_VERSION,
        },
    ),
    description="股票身份映射标准表，用于把历史源代码归一到当前标准股票代码。",
)
def silver_stock_identity_map(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    stock_basic_path = silver_stock_basic_path(lake_root.root())
    namechange_path = silver_namechange_path(lake_root.root())
    target_path = silver_stock_identity_map_path(lake_root.root())
    if not stock_basic_path.exists():
        raise FileNotFoundError(f"Missing silver stock basic file: {stock_basic_path}")
    if not namechange_path.exists():
        raise FileNotFoundError(f"Missing silver namechange file: {namechange_path}")

    seed_rows = load_stock_identity_mapping_seed()
    build_result = build_stock_identity_map_rows(
        stock_basic_rows=_read_stock_basic_rows(duckdb, stock_basic_path),
        seed_rows=seed_rows,
        namechange_codes=_read_namechange_codes(duckdb, namechange_path),
        created_at=datetime.now(STOCK_IDENTITY_MAP_TIMEZONE),
    )
    row_count, columns = write_stock_identity_map_snapshot(
        duckdb=duckdb,
        rows=build_result.rows,
        target_path=target_path,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "stock_basic_file_path": str(stock_basic_path),
                "namechange_file_path": str(namechange_path),
                "seed_file_path": str(STOCK_IDENTITY_MAPPINGS_SEED_PATH),
                "seed_version": STOCK_IDENTITY_MAPPINGS_SEED_VERSION,
                "stock_basic_self_mapping_row_count": build_result.stock_basic_row_count,
                "seed_row_count": build_result.seed_row_count,
                "source_distribution": list(build_result.source_distribution),
                "confidence_distribution": list(build_result.confidence_distribution),
            },
        )
    )
