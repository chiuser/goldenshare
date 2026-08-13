"""Atomic single-partition writer for canonical CN A-share Gold minute bars."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.cn_a_gold_minute_bars import (
    CanonicalGoldMinuteAudit,
    CanonicalGoldMinuteValidationError,
    audit_canonical_gold_minute_relation,
    build_canonical_gold_minute_select_sql,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
    normalize_cn_a_gold_minute_freq,
)


@dataclass(frozen=True, slots=True)
class CanonicalGoldMinuteWriteResult:
    partition_key: str
    target_freq: int
    source_freq: int
    source_path: Path
    target_path: Path
    staging_path: Path
    expected_code_count: int
    source_row_count: int
    output_row_count: int
    expected_row_count: int
    elapsed_ms: float

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "target_freq": self.target_freq,
            "source_freq": self.source_freq,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "staging_path": str(self.staging_path),
            "expected_code_count": self.expected_code_count,
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "expected_row_count": self.expected_row_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _normalized_expected_codes(values: Sequence[object]) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip().upper() for value in values}))
    if not normalized or any(not value for value in normalized):
        raise CanonicalGoldMinuteValidationError(
            "expected code scope must not be empty"
        )
    return normalized


def load_minute_source_codes(connection, source_path: Path) -> tuple[str, ...]:
    if not source_path.is_file():
        raise CanonicalGoldMinuteValidationError(
            f"required Silver minute source is missing: {source_path}"
        )
    rows = connection.execute(
        f"""
        SELECT DISTINCT upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code
        FROM {read_parquet(source_path, hive_partitioning=False)}
        ORDER BY ts_code
        """
    ).fetchall()
    return _normalized_expected_codes(tuple(row[0] for row in rows))


def _assert_same_filesystem(staging_path: Path, target_path: Path) -> None:
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_path.parent.stat().st_dev != target_path.parent.stat().st_dev:
        raise CanonicalGoldMinuteValidationError(
            "Gold minute staging and target must share one filesystem"
        )


def _assert_ready(audit: CanonicalGoldMinuteAudit) -> None:
    if audit.ready:
        return
    raise CanonicalGoldMinuteValidationError(
        "canonical Gold minute staging failed core audit: "
        f"failed_rules={audit.failed_rules}, row_count={audit.row_count}, "
        f"expected_row_count={audit.expected_row_count}"
    )


def write_canonical_gold_minute_partition(
    *,
    duckdb_resource: DuckDBResource,
    source_path: Path,
    target_path: Path,
    staging_path: Path,
    target_freq: int | str,
    partition_key: str,
    expected_codes: Sequence[object] | None = None,
) -> CanonicalGoldMinuteWriteResult:
    """Generate, audit, and atomically promote one Gold frequency partition."""

    started_at = perf_counter()
    normalized_freq = normalize_cn_a_gold_minute_freq(target_freq)
    source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[normalized_freq]
    if not source_path.is_file():
        raise CanonicalGoldMinuteValidationError(
            f"required Silver minute source is missing: {source_path}"
        )
    if target_path.exists():
        raise CanonicalGoldMinuteValidationError(
            f"daily Gold minute writer refuses to overwrite target: {target_path}"
        )
    if staging_path.exists():
        raise CanonicalGoldMinuteValidationError(
            f"run-scoped Gold minute staging already exists: {staging_path}"
        )
    _assert_same_filesystem(staging_path, target_path)

    promoted = False
    try:
        with duckdb_resource.connect() as connection:
            codes = (
                _normalized_expected_codes(expected_codes)
                if expected_codes is not None
                else load_minute_source_codes(connection, source_path)
            )
            source_relation = read_parquet(source_path, hive_partitioning=False)
            source_select = f"SELECT * FROM {source_relation}"
            source_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {source_relation}"
                ).fetchone()[0]
            )
            select_sql = build_canonical_gold_minute_select_sql(
                source_relation_sql=source_select,
                target_freq=normalized_freq,
                partition_key=partition_key,
            )
            connection.execute(copy_query_to_parquet(select_sql, staging_path))
            audit = audit_canonical_gold_minute_relation(
                connection,
                relation_sql=(
                    "SELECT * FROM "
                    f"{read_parquet(staging_path, hive_partitioning=False)}"
                ),
                target_freq=normalized_freq,
                partition_key=partition_key,
                expected_codes=codes,
            )
            _assert_ready(audit)
        os.replace(staging_path, target_path)
        promoted = True
        return CanonicalGoldMinuteWriteResult(
            partition_key=partition_key,
            target_freq=normalized_freq,
            source_freq=source_freq,
            source_path=source_path,
            target_path=target_path,
            staging_path=staging_path,
            expected_code_count=len(codes),
            source_row_count=source_row_count,
            output_row_count=audit.row_count,
            expected_row_count=audit.expected_row_count,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )
    finally:
        if not promoted:
            staging_path.unlink(missing_ok=True)


__all__ = [
    "CanonicalGoldMinuteWriteResult",
    "load_minute_source_codes",
    "write_canonical_gold_minute_partition",
]
