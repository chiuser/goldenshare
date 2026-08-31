"""Raw phase merge writer and Dagster asset for international indexes."""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_index_global_path,
    raw_index_global_staging_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
    TushareResult,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_INDEX_GLOBAL_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_COLUMN_TYPES,
    INDEX_GLOBAL_EXPECTED_CODES,
    INDEX_GLOBAL_FIELDS,
    INDEX_GLOBAL_NORMAL_PHASES,
    INDEX_GLOBAL_REQUEST_LIMIT,
    IndexGlobalRawConfig,
    IndexGlobalRawValidationError,
    build_index_global_request_policy,
    normalize_index_global_numeric_values,
    normalize_index_global_trade_date,
    validate_index_global_phase_rows,
    validate_index_global_raw_config,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_request_policy import (
    TushareRequestPolicy,
    execute_bounded_pages,
)


class IndexGlobalFetchError(RuntimeError):
    """Raised when a bounded Tushare phase cannot be consumed."""


@dataclass(frozen=True)
class IndexGlobalPhaseFetchResult:
    trade_date: str
    probe_phase: str
    rows: tuple[dict[str, object], ...]
    page_count: int
    request_count: int
    retry_count: int
    elapsed_ms: float

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_details(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "probe_phase": self.probe_phase,
            "source_row_count": len(self.rows),
            "page_count": self.page_count,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "source_observation": "empty" if self.empty else "rows",
        }


@dataclass(frozen=True)
class IndexGlobalPhaseSequenceResult:
    trade_date: str
    phase_results: tuple[IndexGlobalPhaseFetchResult, ...]
    merge_results: tuple["IndexGlobalMergeResult", ...]

    @property
    def request_count(self) -> int:
        return sum(result.request_count for result in self.phase_results)

    @property
    def page_count(self) -> int:
        return sum(result.page_count for result in self.phase_results)

    @property
    def retry_count(self) -> int:
        return sum(result.retry_count for result in self.phase_results)


def _extract_index_global_rows(result: TushareResult) -> Sequence[Mapping[str, object]]:
    if not result.rows and not result.columns:
        return ()
    if tuple(result.columns) != INDEX_GLOBAL_FIELDS:
        raise IndexGlobalRawValidationError(
            "index_global Tushare response columns drifted: "
            f"expected {INDEX_GLOBAL_FIELDS}, got {result.columns}"
        )
    return tuple(dict(row) for row in result.rows)


def fetch_index_global_phase(
    *,
    tushare: TushareResource,
    trade_date: str,
    probe_phase: str,
    request_policy: TushareRequestPolicy,
) -> IndexGlobalPhaseFetchResult:
    """Fetch one date/phase through the shared bounded pagination policy."""

    normalized_trade_date = normalize_index_global_trade_date(trade_date)
    if probe_phase not in INDEX_GLOBAL_NORMAL_PHASES and probe_phase != "late_empty":
        raise IndexGlobalRawValidationError(
            f"index_global probe_phase is unsupported: {probe_phase!r}"
        )
    source_trade_date = normalized_trade_date.replace("-", "")
    page_result = execute_bounded_pages(
        request_page=lambda offset: tushare.call(
            "index_global",
            {
                "trade_date": source_trade_date,
                "limit": INDEX_GLOBAL_REQUEST_LIMIT,
                "offset": offset,
            },
            INDEX_GLOBAL_FIELDS,
        ),
        extract_rows=_extract_index_global_rows,
        page_size=INDEX_GLOBAL_REQUEST_LIMIT,
        policy=request_policy,
        scope=f"index_global:{normalized_trade_date}:{probe_phase}",
        row_key=lambda row: (row.get("ts_code"), row.get("trade_date")),
    )
    if not page_result.ready:
        failure_details = (
            page_result.failed_pages[0].to_details()
            if page_result.failed_pages
            else None
        )
        raise IndexGlobalFetchError(
            "index_global bounded phase request failed: "
            f"{page_result.blocked_reason or 'unknown'}; "
            f"request_count={page_result.request_count}, "
            f"retry_count={page_result.retry_count}, "
            f"failed_pages={len(page_result.failed_pages)}, "
            f"failure={failure_details!r}"
        )
    try:
        normalized_rows = validate_index_global_phase_rows(
            page_result.rows,
            trade_date=normalized_trade_date,
            probe_phase=probe_phase,
        )
    except IndexGlobalRawValidationError as exc:
        raise IndexGlobalFetchError(str(exc)) from exc
    return IndexGlobalPhaseFetchResult(
        trade_date=normalized_trade_date,
        probe_phase=probe_phase,
        rows=normalized_rows,
        page_count=page_result.page_count,
        request_count=page_result.request_count,
        retry_count=page_result.retry_count,
        elapsed_ms=page_result.elapsed_ms,
    )


@dataclass(frozen=True)
class IndexGlobalMergeResult:
    partition_key: str
    probe_phase: str
    run_id: str
    target_path: Path
    staging_path: Path | None
    target_existed: bool
    source_row_count: int
    output_row_count: int
    replaced_row_count: int
    promoted: bool


def _describe_columns(connection: Any, path: Path) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(describe_parquet_query(path)).fetchall()
    return tuple((str(row[0]), str(row[1]).upper()) for row in rows)


def _expected_columns() -> tuple[tuple[str, str], ...]:
    return tuple(
        (field, INDEX_GLOBAL_COLUMN_TYPES[field].upper()) for field in INDEX_GLOBAL_FIELDS
    )


def _assert_contract_columns(
    columns: tuple[tuple[str, str], ...], *, label: str
) -> None:
    if columns != _expected_columns():
        raise IndexGlobalRawValidationError(
            f"{label} schema does not match index_global Raw contract: {columns!r}"
        )


def _create_empty_table(connection: Any, table_name: str) -> None:
    definitions = ", ".join(
        f'"{field}" {INDEX_GLOBAL_COLUMN_TYPES[field]}' for field in INDEX_GLOBAL_FIELDS
    )
    connection.execute(f'CREATE TEMP TABLE "{table_name}" ({definitions})')


def _validate_table_rows(connection: Any, table_name: str, *, trade_date: str) -> int:
    source_trade_date = trade_date.replace("-", "")
    expected_code_placeholders = ", ".join("?" for _ in INDEX_GLOBAL_EXPECTED_CODES)
    invalid_scope = connection.execute(
        f"""
        SELECT count(*)
        FROM \"{table_name}\"
        WHERE ts_code IS NULL OR trim(ts_code) = ''
           OR ts_code NOT IN ({expected_code_placeholders})
           OR trade_date IS NULL OR trade_date <> ?
        """,
        [*INDEX_GLOBAL_EXPECTED_CODES, source_trade_date],
    ).fetchone()[0]
    if int(invalid_scope) != 0:
        raise IndexGlobalRawValidationError(
            f"index_global table contains {invalid_scope} out-of-partition or invalid identity rows"
        )

    duplicate_count = connection.execute(
        f"""
        SELECT count(*) FROM (
          SELECT ts_code, trade_date
          FROM \"{table_name}\"
          GROUP BY ts_code, trade_date
          HAVING count(*) > 1
        )
        """
    ).fetchone()[0]
    if int(duplicate_count) != 0:
        raise IndexGlobalRawValidationError(
            f"index_global table contains {duplicate_count} duplicate business keys"
        )

    non_finite = connection.execute(
        f"""
        SELECT count(*) FROM \"{table_name}\"
        WHERE "open" IS NOT NULL AND NOT isfinite("open")
           OR "close" IS NOT NULL AND NOT isfinite("close")
           OR "high" IS NOT NULL AND NOT isfinite("high")
           OR "low" IS NOT NULL AND NOT isfinite("low")
           OR "pre_close" IS NOT NULL AND NOT isfinite("pre_close")
           OR "change" IS NOT NULL AND NOT isfinite("change")
           OR "pct_chg" IS NOT NULL AND NOT isfinite("pct_chg")
           OR "swing" IS NOT NULL AND NOT isfinite("swing")
           OR "vol" IS NOT NULL AND NOT isfinite("vol")
           OR "amount" IS NOT NULL AND NOT isfinite("amount")
        """
    ).fetchone()[0]
    if int(non_finite) != 0:
        raise IndexGlobalRawValidationError(
            f"index_global table contains {non_finite} non-finite numeric rows"
        )
    return int(connection.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0])


def _load_phase_rows(
    connection: Any,
    rows: Sequence[Mapping[str, object]],
) -> None:
    _create_empty_table(connection, "phase_rows")
    if not rows:
        return
    placeholders = ", ".join("?" for _ in INDEX_GLOBAL_FIELDS)
    values = [tuple(row[field] for field in INDEX_GLOBAL_FIELDS) for row in rows]
    connection.executemany(
        f"INSERT INTO phase_rows VALUES ({placeholders})",
        values,
    )


def _load_existing_rows(connection: Any, target_path: Path) -> tuple[bool, int]:
    if not target_path.exists():
        _create_empty_table(connection, "existing_rows")
        return False, 0
    _assert_contract_columns(
        _describe_columns(connection, target_path), label="existing target"
    )
    columns_sql = ", ".join(f'"{field}"' for field in INDEX_GLOBAL_FIELDS)
    connection.execute(
        f'CREATE TEMP TABLE existing_rows AS SELECT {columns_sql} FROM {read_parquet(target_path)}'
    )
    return True, int(connection.execute("SELECT count(*) FROM existing_rows").fetchone()[0])


def _merged_query() -> str:
    columns_sql = ", ".join(f'"{field}"' for field in INDEX_GLOBAL_FIELDS)
    return f"""
    WITH combined AS (
      SELECT {columns_sql}, 0 AS merge_rank FROM existing_rows
      UNION ALL
      SELECT {columns_sql}, 1 AS merge_rank FROM phase_rows
    ), ranked AS (
      SELECT {columns_sql},
             row_number() OVER (
               PARTITION BY ts_code, trade_date
               ORDER BY merge_rank DESC
             ) AS row_number
      FROM combined
    )
    SELECT {columns_sql}
    FROM ranked
    WHERE row_number = 1
    ORDER BY ts_code, trade_date
    """


def _replaced_row_count(connection: Any) -> int:
    columns = [field for field in INDEX_GLOBAL_FIELDS if field not in {"ts_code", "trade_date"}]
    comparisons = " OR ".join(
        f'e."{field}" IS DISTINCT FROM p."{field}"' for field in columns
    )
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM existing_rows e
            JOIN phase_rows p USING (ts_code, trade_date)
            WHERE {comparisons}
            """
        ).fetchone()[0]
    )


def _validate_staging(
    connection: Any,
    staging_path: Path,
    *,
    trade_date: str,
    expected_row_count: int,
) -> None:
    _assert_contract_columns(
        _describe_columns(connection, staging_path), label="staging"
    )
    connection.execute(
        f'CREATE TEMP TABLE staging_rows AS SELECT * FROM {read_parquet(staging_path)}'
    )
    actual_row_count = _validate_table_rows(
        connection, "staging_rows", trade_date=trade_date
    )
    if actual_row_count != expected_row_count:
        raise IndexGlobalRawValidationError(
            f"staging row count changed: expected {expected_row_count}, got {actual_row_count}"
        )
    return actual_row_count


def merge_index_global_phase(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
    probe_phase: str,
    phase_rows: Sequence[Mapping[str, object]],
    run_id: str,
) -> IndexGlobalMergeResult:
    """Merge one validated phase into one Raw date file atomically."""

    normalized_trade_date = normalize_index_global_trade_date(trade_date)
    normalized_rows = validate_index_global_phase_rows(
        phase_rows,
        trade_date=normalized_trade_date,
        probe_phase=probe_phase,
    )
    normalized_rows = tuple(
        normalize_index_global_numeric_values(row) for row in normalized_rows
    )

    target_path = raw_index_global_path(lake_root_path, normalized_trade_date)
    staging_path = raw_index_global_staging_path(
        lake_root_path, run_id, normalized_trade_date, probe_phase
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.exists():
        staging_path.unlink()

    target_existed = False
    promoted = False
    try:
        with duckdb_resource.connect() as connection:
            target_existed, existing_row_count = _load_existing_rows(connection, target_path)
            if target_existed:
                _validate_table_rows(
                    connection, "existing_rows", trade_date=normalized_trade_date
                )
                if not normalized_rows:
                    return IndexGlobalMergeResult(
                        partition_key=normalized_trade_date,
                        probe_phase=probe_phase,
                        run_id=run_id,
                        target_path=target_path,
                        staging_path=None,
                        target_existed=True,
                        source_row_count=0,
                        output_row_count=existing_row_count,
                        replaced_row_count=0,
                        promoted=False,
                    )
            _load_phase_rows(connection, normalized_rows)
            _validate_table_rows(
                connection, "phase_rows", trade_date=normalized_trade_date
            )
            replaced_row_count = _replaced_row_count(connection) if normalized_rows else 0
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(
                copy_query_to_parquet(_merged_query(), staging_path)
            )
            output_row_count = _validate_staging(
                connection,
                staging_path,
                trade_date=normalized_trade_date,
                expected_row_count=(
                    int(
                        connection.execute(
                            "SELECT count(*) FROM (" + _merged_query() + ")"
                        ).fetchone()[0]
                    )
                ),
            )
        os.replace(staging_path, target_path)
        promoted = True
        return IndexGlobalMergeResult(
            partition_key=normalized_trade_date,
            probe_phase=probe_phase,
            run_id=run_id,
            target_path=target_path,
            staging_path=staging_path,
            target_existed=target_existed,
            source_row_count=len(normalized_rows),
            output_row_count=output_row_count,
            replaced_row_count=replaced_row_count,
            promoted=True,
        )
    finally:
        if not promoted and staging_path.exists():
            staging_path.unlink()


def run_index_global_phase_sequence(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    trade_date: str,
    run_id: str,
    request_policy: TushareRequestPolicy,
    phases: Sequence[str] = INDEX_GLOBAL_NORMAL_PHASES,
) -> IndexGlobalPhaseSequenceResult:
    """Run the five phases serially against a caller-owned temporary lake."""

    normalized_trade_date = normalize_index_global_trade_date(trade_date)
    if tuple(phases) != tuple(dict.fromkeys(phases)):
        raise IndexGlobalRawValidationError("index_global phases must be unique")
    if any(phase not in INDEX_GLOBAL_NORMAL_PHASES for phase in phases):
        raise IndexGlobalRawValidationError(
            "index_global sequence only accepts the five normal probe phases"
        )

    phase_results: list[IndexGlobalPhaseFetchResult] = []
    merge_results: list[IndexGlobalMergeResult] = []
    for phase in phases:
        fetched = fetch_index_global_phase(
            tushare=tushare,
            trade_date=normalized_trade_date,
            probe_phase=phase,
            request_policy=request_policy,
        )
        merged = merge_index_global_phase(
            lake_root_path=lake_root_path,
            duckdb_resource=duckdb_resource,
            trade_date=normalized_trade_date,
            probe_phase=phase,
            phase_rows=fetched.rows,
            run_id=run_id,
        )
        phase_results.append(fetched)
        merge_results.append(merged)
    return IndexGlobalPhaseSequenceResult(
        trade_date=normalized_trade_date,
        phase_results=tuple(phase_results),
        merge_results=tuple(merge_results),
    )


@dg.asset(
    name="raw_index_global",
    partitions_def=cn_global_index_trade_days,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_global",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_index_global_raw_by_trade_date",
        column_schema=RAW_INDEX_GLOBAL_SCHEMA,
        path_template=lake_path_template(
            raw_index_global_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="index_global",
        source_category_path="指数专题",
        source_doc="docs/sources/tushare/指数专题/0211_国际指数.md",
        extra_metadata={
            "partition_set": cn_global_index_trade_days.name,
            "write_boundary": "p5_dagster_asset",
        },
    ),
    description="Tushare 国际指数日线 Raw，按自然日和阶段增量合并。",
)
def raw_index_global(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    config: IndexGlobalRawConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = validate_index_global_raw_config(
        config, partition_key=context.partition_key
    )
    fetched = fetch_index_global_phase(
        tushare=tushare,
        trade_date=partition_key,
        probe_phase=config.probe_phase,
        request_policy=build_index_global_request_policy(),
    )
    merged = merge_index_global_phase(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        trade_date=partition_key,
        probe_phase=config.probe_phase,
        phase_rows=fetched.rows,
        run_id=context.run_id,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=merged.target_path,
            row_count=merged.output_row_count,
            observed_columns=INDEX_GLOBAL_FIELDS,
            extra_metadata={
                "trade_date": partition_key,
                "probe_phase": config.probe_phase,
                "slot_key": config.slot_key,
                "attempt": config.attempt,
                "late_empty_attempt": config.late_empty_attempt,
                "source_method": "tushare_index_global",
                "source_row_count": len(fetched.rows),
                "merged_row_count": merged.output_row_count,
                "replaced_row_count": merged.replaced_row_count,
                "request_count": fetched.request_count,
                "page_count": fetched.page_count,
                "retry_count": fetched.retry_count,
                "elapsed_ms": round(fetched.elapsed_ms, 3),
                "target_path": str(merged.target_path),
            },
        )
    )
