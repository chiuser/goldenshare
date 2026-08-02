"""Manual Silver snapshot for the versioned Eastmoney industry hierarchy."""

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    silver_dc_index_path,
    silver_dc_industry_hierarchy_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import (
    DcIndustryHierarchyConfig,
    normalize_iso_trade_date,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.seeds.board.eastmoney_dc_industry_hierarchy import (
    EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS,
    EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH,
    load_eastmoney_dc_industry_hierarchy_seed,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


_BOARD_CODE_RE = re.compile(r"^BK[0-9]{4}\.DC$")
_INDUSTRY_LEVEL_NAME_BY_LEVEL = {
    1: "东财一级行业",
    2: "东财二级行业",
    3: "东财三级行业",
}
_REFERENCE_LEVEL_TO_INDUSTRY_LEVEL = {
    level_name: level
    for level, level_name in _INDUSTRY_LEVEL_NAME_BY_LEVEL.items()
}
_EXPECTED_COLUMNS = tuple(column.name for column in SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA)
_EXPECTED_COLUMN_TYPES = tuple(column.type for column in SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA)
_OUTPUT_COLUMN_PROJECTION = ", ".join(_EXPECTED_COLUMNS)
LOGGER = DgStdoutLogger("dc_industry_hierarchy")


class DcIndustryHierarchyValidationError(RuntimeError):
    """Raised when a hierarchy snapshot cannot satisfy its strict contract."""


@dataclass(frozen=True, slots=True)
class DcIndustryHierarchyReference:
    trade_date: str
    path: Path
    node_count: int
    level_counts: tuple[tuple[int, int], ...]
    code_hash: str


@dataclass(frozen=True, slots=True)
class DcIndustryHierarchyReferenceAudit:
    reference: DcIndustryHierarchyReference
    missing_seed_node_count: int
    extra_reference_node_count: int
    missing_seed_node_samples: tuple[tuple[int, str], ...]
    extra_reference_node_samples: tuple[tuple[str, str], ...]

    def assert_closed(self) -> None:
        if self.missing_seed_node_count or self.extra_reference_node_count:
            raise DcIndustryHierarchyValidationError(
                "Eastmoney industry hierarchy seed and silver_dc_index reference "
                "must map two ways by level and name: "
                f"missing_seed_node_count={self.missing_seed_node_count}, "
                f"extra_reference_node_count={self.extra_reference_node_count}, "
                f"missing_samples={self.missing_seed_node_samples[:20]}, "
                f"extra_samples={self.extra_reference_node_samples[:20]}."
            )


@dataclass(frozen=True, slots=True)
class DcIndustryHierarchyWriteResult:
    target_path: Path
    row_count: int
    observed_columns: tuple[str, ...]
    level_counts: tuple[tuple[int, int], ...]
    reference: DcIndustryHierarchyReference
    elapsed_ms: float


def _reference_select_sql(path: Path) -> str:
    return f"""
        SELECT
          upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
          trim(CAST(name AS VARCHAR)) AS name,
          trim(CAST(level AS VARCHAR)) AS level
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE trim(CAST(idx_type AS VARCHAR)) = '行业板块'
    """


def _reference_industry_level_sql(level_expression: str) -> str:
    """Map the authoritative Chinese dc_index level labels to integer levels."""

    return f"""
        CASE trim(CAST({level_expression} AS VARCHAR))
          WHEN '东财一级行业' THEN 1
          WHEN '东财二级行业' THEN 2
          WHEN '东财三级行业' THEN 3
        END
    """


def _seed_select_sql() -> str:
    return f"""
        SELECT
          trim(CAST(node_path AS VARCHAR)) AS node_path,
          NULLIF(trim(CAST(parent_path AS VARCHAR)), '') AS parent_path,
          CAST(industry_level AS INTEGER) AS industry_level,
          trim(CAST(name AS VARCHAR)) AS name,
          CAST(display_order AS INTEGER) AS display_order
        FROM read_csv_auto({duckdb_string(EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH)}, header=true)
    """


def _reference_hash(rows: list[tuple[str, str, str]]) -> str:
    canonical = "\n".join(
        f"{level}\t{name}\t{ts_code}"
        for ts_code, name, level in sorted(rows, key=lambda row: (row[2], row[1], row[0]))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_dc_industry_hierarchy_reference(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    reference_trade_date: str,
) -> DcIndustryHierarchyReference:
    """Read and structurally validate exactly one dc_index industry reference file."""

    trade_date = normalize_iso_trade_date(
        reference_trade_date,
        field_name="reference_trade_date",
    )
    path = silver_dc_index_path(lake_root_path, trade_date)
    if not path.is_file():
        raise DcIndustryHierarchyValidationError(
            f"Missing silver_dc_index reference file: {path}"
        )

    with duckdb_resource.connect() as connection:
        rows = [
            (str(row[0] or "").strip(), str(row[1] or "").strip(), str(row[2] or "").strip())
            for row in connection.execute(_reference_select_sql(path)).fetchall()
        ]

    invalid_keys = [
        row
        for row in rows
        if not _BOARD_CODE_RE.fullmatch(row[0]) or not row[1] or row[2] not in _REFERENCE_LEVEL_TO_INDUSTRY_LEVEL
    ]
    level_name_counts = Counter((level, name) for _, name, level in rows)
    duplicate_level_names = sorted(
        item for item, count in level_name_counts.items() if count > 1
    )
    code_counts = Counter(ts_code for ts_code, _, _ in rows)
    duplicate_codes = sorted(code for code, count in code_counts.items() if count > 1)
    level_counts = Counter(
        _REFERENCE_LEVEL_TO_INDUSTRY_LEVEL[level]
        for _, _, level in rows
        if level in _REFERENCE_LEVEL_TO_INDUSTRY_LEVEL
    )
    if (
        invalid_keys
        or duplicate_level_names
        or duplicate_codes
        or dict(level_counts) != EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS
    ):
        raise DcIndustryHierarchyValidationError(
            "silver_dc_index industry reference must contain the exact current Eastmoney "
            "industry directory: "
            f"invalid_count={len(invalid_keys)}, "
            f"duplicate_level_name_count={len(duplicate_level_names)}, "
            f"duplicate_code_count={len(duplicate_codes)}, "
            f"level_counts={dict(level_counts)}, "
            f"invalid_samples={invalid_keys[:20]}, "
            f"duplicate_level_name_samples={duplicate_level_names[:20]}, "
            f"duplicate_code_samples={duplicate_codes[:20]}."
        )

    return DcIndustryHierarchyReference(
        trade_date=trade_date,
        path=path,
        node_count=len(rows),
        level_counts=tuple(sorted(level_counts.items())),
        code_hash=_reference_hash(rows),
    )


def audit_dc_industry_hierarchy_reference(
    *,
    duckdb_resource: DuckDBResource,
    reference: DcIndustryHierarchyReference,
) -> DcIndustryHierarchyReferenceAudit:
    """Compare the immutable seed and one validated reference directory two ways."""

    load_eastmoney_dc_industry_hierarchy_seed()
    with duckdb_resource.connect() as connection:
        seed_sql = _seed_select_sql()
        reference_sql = _reference_select_sql(reference.path)
        missing_rows = connection.execute(
            f"""
            WITH seed AS ({seed_sql}), reference AS ({reference_sql})
            SELECT seed.industry_level, seed.name
            FROM seed
            LEFT JOIN reference
              ON {_reference_industry_level_sql('reference.level')} = seed.industry_level
             AND reference.name = seed.name
            WHERE reference.ts_code IS NULL
            ORDER BY seed.industry_level, seed.name
            """
        ).fetchall()
        extra_rows = connection.execute(
            f"""
            WITH seed AS ({seed_sql}), reference AS ({reference_sql})
            SELECT reference.level, reference.name
            FROM reference
            LEFT JOIN seed
              ON {_reference_industry_level_sql('reference.level')} = seed.industry_level
             AND reference.name = seed.name
            WHERE seed.node_path IS NULL
            ORDER BY reference.level, reference.name
            """
        ).fetchall()

    return DcIndustryHierarchyReferenceAudit(
        reference=reference,
        missing_seed_node_count=len(missing_rows),
        extra_reference_node_count=len(extra_rows),
        missing_seed_node_samples=tuple(
            (int(level), str(name)) for level, name in missing_rows[:20]
        ),
        extra_reference_node_samples=tuple(
            (str(level), str(name)) for level, name in extra_rows[:20]
        ),
    )


def build_dc_industry_hierarchy_select_sql(
    *,
    reference: DcIndustryHierarchyReference,
) -> str:
    """Return the single set-based hierarchy build query for the current seed."""

    seed_sql = _seed_select_sql()
    reference_sql = _reference_select_sql(reference.path)
    source_received_date = load_eastmoney_dc_industry_hierarchy_seed().source_received_date.isoformat()
    return f"""
        WITH seed AS ({seed_sql}),
        reference AS ({reference_sql}),
        mapped AS (
          SELECT
            reference.ts_code,
            seed.name,
            seed.industry_level,
            CASE seed.industry_level
              WHEN 1 THEN '东财一级行业'
              WHEN 2 THEN '东财二级行业'
              WHEN 3 THEN '东财三级行业'
            END AS industry_level_name,
            seed.node_path,
            seed.parent_path,
            seed.display_order
          FROM seed
          JOIN reference
            ON {_reference_industry_level_sql('reference.level')} = seed.industry_level
           AND reference.name = seed.name
        )
        SELECT
          current_node.ts_code,
          current_node.name,
          current_node.industry_level,
          current_node.industry_level_name,
          parent_node.ts_code AS parent_ts_code,
          parent_node.name AS parent_name,
          root_node.ts_code AS root_ts_code,
          root_node.name AS root_name,
          replace(current_node.node_path, '/', ' > ') AS hierarchy_path,
          NOT EXISTS (
            SELECT 1
            FROM mapped child_node
            WHERE child_node.parent_path = current_node.node_path
          ) AS is_leaf,
          current_node.display_order,
          {duckdb_string(load_eastmoney_dc_industry_hierarchy_seed().version)} AS baseline_version,
          CAST({duckdb_string(source_received_date)} AS DATE) AS source_received_date,
          CAST({duckdb_string(reference.trade_date)} AS DATE) AS code_reference_trade_date
        FROM mapped current_node
        LEFT JOIN mapped parent_node
          ON parent_node.node_path = current_node.parent_path
        JOIN mapped root_node
          ON root_node.node_path = split_part(current_node.node_path, '/', 1)
        ORDER BY current_node.display_order
    """


def _snapshot_validation_failures(
    *,
    connection: Any,
    path: Path,
    reference: DcIndustryHierarchyReference,
) -> dict[str, int]:
    observed_schema = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    observed_columns = tuple(str(row[0]) for row in observed_schema)
    observed_types = tuple(str(row[1]) for row in observed_schema)
    schema_mismatch = int(
        observed_columns != _EXPECTED_COLUMNS or observed_types != _EXPECTED_COLUMN_TYPES
    )
    if schema_mismatch:
        return {
            "schema_mismatch": schema_mismatch,
            "row_count_mismatch": 0,
            "level_count_mismatch": 0,
            "invalid_key_count": 0,
            "duplicate_ts_code_count": 0,
            "duplicate_hierarchy_path_count": 0,
            "invalid_root_count": 0,
            "invalid_parent_count": 0,
            "invalid_root_reference_count": 0,
            "baseline_mismatch_count": 0,
        }
    relation = read_parquet(path, hive_partitioning=False)
    row_count = int(connection.execute(count_parquet_query(path)).fetchone()[0])
    level_counts = dict(
        (int(level), int(count))
        for level, count in connection.execute(
            f"""
            SELECT industry_level, count(*)
            FROM {relation}
            GROUP BY industry_level
            ORDER BY industry_level
            """
        ).fetchall()
    )
    key_row = connection.execute(
        f"""
        SELECT
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = ''
               OR hierarchy_path IS NULL OR trim(hierarchy_path) = ''
               OR NOT regexp_matches(ts_code, '^BK[0-9]{{4}}\\.DC$')
          ) AS invalid_key_count,
          count(*) - count(DISTINCT ts_code) AS duplicate_ts_code_count,
          count(*) - count(DISTINCT hierarchy_path) AS duplicate_hierarchy_path_count
        FROM {relation}
        """
    ).fetchone()
    closure_row = connection.execute(
        f"""
        WITH output AS (SELECT {_OUTPUT_COLUMN_PROJECTION} FROM {relation})
        SELECT
          count(*) FILTER (
            WHERE child.industry_level = 1
              AND (
                child.parent_ts_code IS NOT NULL
                OR child.parent_name IS NOT NULL
                OR child.root_ts_code <> child.ts_code
                OR child.root_name <> child.name
              )
          ) AS invalid_root_count,
          count(*) FILTER (
            WHERE child.industry_level > 1
              AND (
                child.parent_ts_code IS NULL
                OR child.parent_name IS NULL
                OR parent.ts_code IS NULL
                OR parent.industry_level <> child.industry_level - 1
              )
          ) AS invalid_parent_count,
          count(*) FILTER (
            WHERE root.ts_code IS NULL
               OR root.industry_level <> 1
               OR root.name <> child.root_name
          ) AS invalid_root_reference_count
        FROM output child
        LEFT JOIN output parent ON parent.ts_code = child.parent_ts_code
        LEFT JOIN output root ON root.ts_code = child.root_ts_code
        """
    ).fetchone()
    baseline = load_eastmoney_dc_industry_hierarchy_seed()
    baseline_row = connection.execute(
        f"""
        SELECT count(*)
        FROM {relation}
        WHERE baseline_version <> {duckdb_string(baseline.version)}
           OR source_received_date <> CAST({duckdb_string(baseline.source_received_date.isoformat())} AS DATE)
           OR code_reference_trade_date <> CAST({duckdb_string(reference.trade_date)} AS DATE)
        """
    ).fetchone()
    return {
        "schema_mismatch": schema_mismatch,
        "row_count_mismatch": int(row_count != sum(EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS.values())),
        "level_count_mismatch": int(level_counts != EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS),
        "invalid_key_count": int(key_row[0]),
        "duplicate_ts_code_count": int(key_row[1]),
        "duplicate_hierarchy_path_count": int(key_row[2]),
        "invalid_root_count": int(closure_row[0]),
        "invalid_parent_count": int(closure_row[1]),
        "invalid_root_reference_count": int(closure_row[2]),
        "baseline_mismatch_count": int(baseline_row[0]),
    }


def _assert_snapshot_valid(
    *,
    connection: Any,
    path: Path,
    reference: DcIndustryHierarchyReference,
) -> tuple[int, tuple[str, ...], tuple[tuple[int, int], ...]]:
    failures = _snapshot_validation_failures(
        connection=connection,
        path=path,
        reference=reference,
    )
    failed_rules = [name for name, count in failures.items() if count]
    if failed_rules:
        raise DcIndustryHierarchyValidationError(
            "dc industry hierarchy snapshot validation failed: "
            f"failed_rules={failed_rules}, failures={failures}."
        )
    relation = read_parquet(path, hive_partitioning=False)
    row_count = int(connection.execute(count_parquet_query(path)).fetchone()[0])
    level_counts = tuple(
        (int(level), int(count))
        for level, count in connection.execute(
            f"""
            SELECT industry_level, count(*)
            FROM {relation}
            GROUP BY industry_level
            ORDER BY industry_level
            """
        ).fetchall()
    )
    return row_count, _EXPECTED_COLUMNS, level_counts


def write_silver_dc_industry_hierarchy_snapshot(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    reference_trade_date: str,
) -> DcIndustryHierarchyWriteResult:
    """Build, validate, and atomically promote the full hierarchy snapshot."""

    started_at = perf_counter()
    reference = load_dc_industry_hierarchy_reference(
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb_resource,
        reference_trade_date=reference_trade_date,
    )
    audit = audit_dc_industry_hierarchy_reference(
        duckdb_resource=duckdb_resource,
        reference=reference,
    )
    audit.assert_closed()

    target_path = silver_dc_industry_hierarchy_path(lake_root_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
    try:
        with connect_configured_duckdb() as connection:
            connection.execute(
                copy_query_to_parquet(
                    build_dc_industry_hierarchy_select_sql(reference=reference),
                    staging_path,
                )
            )
            row_count, observed_columns, level_counts = _assert_snapshot_valid(
                connection=connection,
                path=staging_path,
                reference=reference,
            )
        os.replace(staging_path, target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return DcIndustryHierarchyWriteResult(
        target_path=target_path,
        row_count=row_count,
        observed_columns=observed_columns,
        level_counts=level_counts,
        reference=reference,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


@dg.asset(
    name="silver_dc_industry_hierarchy",
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_industry_hierarchy",
        source_system=SourceSystem.SEED,
        data_contract="eastmoney_dc_industry_hierarchy_with_board_codes_full_snapshot",
        column_schema=SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA,
        path_template=lake_path_template(
            silver_dc_industry_hierarchy_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "seed_version": load_eastmoney_dc_industry_hierarchy_seed().version,
            "code_reference_asset": "silver_dc_index",
            "write_boundary": "duckdb_set_based_atomic_replace",
        },
    ),
    description=(
        "东方财富三级行业层级 Silver 全量快照；以版本化东财层级 seed 为分类事实，"
        "按人工指定的 dc_index 交易日补齐当前 BK 代码。"
    ),
)
def silver_dc_industry_hierarchy(
    config: DcIndustryHierarchyConfig,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    reference_trade_date = normalize_iso_trade_date(
        config.reference_trade_date,
        field_name="reference_trade_date",
    )
    LOGGER.stdout(
        "dc_industry_hierarchy_started",
        reference_trade_date=reference_trade_date,
    )
    try:
        result = write_silver_dc_industry_hierarchy_snapshot(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            reference_trade_date=reference_trade_date,
        )
    except DcIndustryHierarchyValidationError as error:
        LOGGER.stdout(
            "dc_industry_hierarchy_validation_failed",
            reference_trade_date=reference_trade_date,
            reason=str(error)[:240],
        )
        raise

    LOGGER.stdout(
        "dc_industry_hierarchy_reference_validated",
        reference_trade_date=result.reference.trade_date,
        reference_node_count=result.reference.node_count,
    )
    LOGGER.stdout(
        "dc_industry_hierarchy_completed",
        output_row_count=result.row_count,
        reference_trade_date=result.reference.trade_date,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.row_count,
            observed_columns=result.observed_columns,
            extra_metadata={
                "summary": "已生成东方财富三级行业层级快照，并补齐当前 BK 代码。",
                "next_action": "等待唯一核心 check 通过后供板块层级分析和下游 join 使用。",
                "result_status": "written",
                "diagnostic_ref": "完整诊断看核心 check、版本化 seed 和 run stdout。",
                "seed_file_path": str(EASTMONEY_DC_INDUSTRY_HIERARCHY_SEED_PATH),
                "seed_sha256": load_eastmoney_dc_industry_hierarchy_seed().seed_sha256,
                "seed_node_count": sum(EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS.values()),
                "code_reference_trade_date": result.reference.trade_date,
                "code_reference_file_path": str(result.reference.path),
                "code_reference_node_count": result.reference.node_count,
                "code_reference_hash": result.reference.code_hash,
                "level_count_distribution": dict(result.level_counts),
                "elapsed_ms": round(result.elapsed_ms, 3),
            },
        )
    )


__all__ = [
    "DcIndustryHierarchyReference",
    "DcIndustryHierarchyReferenceAudit",
    "DcIndustryHierarchyValidationError",
    "DcIndustryHierarchyWriteResult",
    "SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA",
    "audit_dc_industry_hierarchy_reference",
    "build_dc_industry_hierarchy_select_sql",
    "load_dc_industry_hierarchy_reference",
    "silver_dc_industry_hierarchy",
    "write_silver_dc_industry_hierarchy_snapshot",
]
