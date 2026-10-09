"""Bounded same-day relation predicates shared by checks and readiness scans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from orchestrator.defs.asset_guards.dc_board_quote_coverage import (
    AWAITING_QUOTE,
    BoardQuoteCoverageResult,
    batch_board_quote_coverage,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.dc_board import DC_INDEX_PLACEHOLDER_SQL


@dataclass(frozen=True, slots=True)
class BoardRelationResult:
    failed_count: int
    samples: tuple[dict[str, object], ...]
    coverage: BoardQuoteCoverageResult | None = None

    def __iter__(self):
        yield self.failed_count
        yield self.samples

    def metadata(self):
        return self.coverage.metadata() if self.coverage else {}


def quote_gap_codes(connection, *, source_path: Path, index_path: Path) -> tuple[str, ...]:
    return tuple(row[0] for row in connection.execute(
        f"SELECT DISTINCT ts_code FROM {read_parquet(index_path, hive_partitioning=False)} "
        f"WHERE NOT ({DC_INDEX_PLACEHOLDER_SQL}) EXCEPT "
        f"SELECT DISTINCT ts_code FROM {read_parquet(source_path, hive_partitioning=False)}"
    ).fetchall())


def batch_board_relation_coverage(connection, *, lake_root: Path,
    paths_by_date: Mapping[str, tuple[Path, Path]], duckdb_resource=None):
    gaps = {day: quote_gap_codes(connection, source_path=paths[0], index_path=paths[1])
            for day, paths in paths_by_date.items() if paths[1].is_file()}
    coverage = batch_board_quote_coverage(lake_root=lake_root, gaps_by_date=gaps,
                                         duckdb_resource=duckdb_resource or DuckDBResource())
    for day, result in coverage.items():
        source_path, index_path = paths_by_date[day]
        count = connection.execute(
            f"SELECT (SELECT count(DISTINCT ts_code) FROM {read_parquet(index_path, hive_partitioning=False)} "
            f"WHERE NOT ({DC_INDEX_PLACEHOLDER_SQL})), "
            f"(SELECT count(DISTINCT ts_code) FROM {read_parquet(source_path, hive_partitioning=False)})"
        ).fetchone()
        samples = sorted(x.code for x in result.details)[:5]
        labels = tuple(connection.execute(
            f"SELECT ts_code, name, idx_type FROM {read_parquet(index_path, hive_partitioning=False)} "
            "WHERE ts_code IN (SELECT unnest(?)) ORDER BY ts_code", [samples]
        ).fetchall()) if samples else ()
        coverage[day] = replace(result, index_count=int(count[0]), daily_count=int(count[1]), sample_labels=labels)
    return coverage


def _relation_failure(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
    coverage: BoardQuoteCoverageResult | None = None,
) -> BoardRelationResult:
    if not index_path.exists():
        return BoardRelationResult(1, ({"reason_code": "index_partition_missing", "path": str(index_path)},))
    source_relation = read_parquet(source_path, hive_partitioning=False)
    index_relation = read_parquet(index_path, hive_partitioning=False)
    if mode == "index_subset_daily":
        if coverage is None:
            raise ValueError("daily relation requires explicit shared quote coverage evidence")
        failures = tuple(x for x in coverage.details if x.state != AWAITING_QUOTE)
        return BoardRelationResult(len(failures), tuple(
            {"ts_code": x.code, "reason_code": x.state, "observed_quote_date": x.observed_quote_date}
            for x in failures[:5]), coverage)
    elif mode == "member_subset_index":
        sql = f"""
        SELECT count(*) FROM (
            SELECT DISTINCT ts_code FROM {source_relation}
            EXCEPT
            SELECT DISTINCT ts_code FROM {index_relation}
        )
        """
        sample_sql = f"""
        SELECT ts_code, 'member_code_not_in_index' AS reason_code
        FROM (
            SELECT DISTINCT ts_code FROM {source_relation}
            EXCEPT
            SELECT DISTINCT ts_code FROM {index_relation}
        )
        LIMIT 5
        """
    else:
        raise ValueError(f"unknown board relation mode: {mode}")
    failure_count = int(connection.execute(sql).fetchone()[0])
    rows = connection.execute(sample_sql).fetchall() if failure_count else ()
    return BoardRelationResult(failure_count, tuple(
        {"ts_code": row[0], "reason_code": row[1]} for row in rows
    ))


def audit_raw_board_relation(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
    coverage: BoardQuoteCoverageResult | None = None,
) -> BoardRelationResult:
    return _relation_failure(
        connection,
        source_path=source_path,
        index_path=index_path,
        mode=mode,
        coverage=coverage,
    )


def audit_silver_board_relation(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
    coverage: BoardQuoteCoverageResult | None = None,
) -> BoardRelationResult:
    return _relation_failure(
        connection,
        source_path=source_path,
        index_path=index_path,
        mode=mode,
        coverage=coverage,
    )


__all__ = ["audit_raw_board_relation", "audit_silver_board_relation"]
