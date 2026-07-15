"""Bounded, atomic repair writer for ``gold_dc_daily_technical``.

The normal Gold writer intentionally skips an existing valid partition.  A
repair has different semantics: it recomputes every explicitly selected
partition, validates all staging files, and only then promotes them.  This
module remains Dagster-free; the repair op owns event attribution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import os
from time import perf_counter
from uuid import uuid4

from orchestrator.defs.asset_guards.dc_daily_silver_repair_producer import (
    source_revision_for_silver_paths,
)
from orchestrator.defs.assets.dc_daily_technical import (
    DcDailyTechnicalValidationError,
    DcDailyTechnicalWriteResult,
    _indicator_sql,
    _peak_memory_bytes,
    _read_paths,
    _schema_mismatches,
    _source_sql,
    _validate_output_against_source,
    _validate_source,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import gold_dc_daily_technical_path, silver_dc_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.silver_repair import (
    SilverRepairBatch,
    validate_silver_repair_batch,
)


MAX_GOLD_REPAIR_DATES = 60


class DcDailyTechnicalRepairValidationError(ValueError):
    """Raised when a bounded Gold repair cannot be safely published."""


@dataclass(frozen=True, slots=True)
class DcDailyTechnicalRepairWriteResult:
    """Auditable result of one all-or-nothing bounded Gold repair attempt."""

    upstream_batch_id: str
    source_revision: str
    source_repair_start_trade_date: str
    source_repair_end_trade_date: str
    indicator_recompute_start_trade_date: str
    indicator_recompute_end_trade_date: str
    context_start_trade_date: str
    target_frontier_trade_date: str
    source_file_count: int
    source_row_count: int
    rewritten_partition_count: int
    output_row_count: int
    elapsed_ms: float
    duckdb_elapsed_ms: float
    staging_write_elapsed_ms: float
    promote_elapsed_ms: float
    peak_memory_bytes: int
    partition_results: tuple[DcDailyTechnicalWriteResult, ...]

    def to_metadata(self) -> dict[str, object]:
        return {
            "source_asset": "silver_dc_daily",
            "target_asset": "gold_dc_daily_technical",
            "upstream_batch_id": self.upstream_batch_id,
            "source_revision": self.source_revision,
            "source_repair_start_trade_date": self.source_repair_start_trade_date,
            "source_repair_end_trade_date": self.source_repair_end_trade_date,
            "indicator_recompute_start_trade_date": self.indicator_recompute_start_trade_date,
            "indicator_recompute_end_trade_date": self.indicator_recompute_end_trade_date,
            "context_start_trade_date": self.context_start_trade_date,
            "target_frontier_trade_date": self.target_frontier_trade_date,
            "source_file_count": self.source_file_count,
            "source_row_count": self.source_row_count,
            "rewritten_partition_count": self.rewritten_partition_count,
            "output_row_count": self.output_row_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "duckdb_elapsed_ms": round(self.duckdb_elapsed_ms, 3),
            "staging_write_elapsed_ms": round(self.staging_write_elapsed_ms, 3),
            "promote_elapsed_ms": round(self.promote_elapsed_ms, 3),
            "peak_memory_bytes": self.peak_memory_bytes,
            "write_mode": "duckdb_bounded_repair_stage_validate_atomic_replace",
        }


def write_gold_dc_daily_technical_repair_batch(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    batch: SilverRepairBatch,
    expected_trade_dates: Sequence[object],
    registered_trade_dates: Sequence[object],
    max_indicator_recompute_dates: int = MAX_GOLD_REPAIR_DATES,
) -> DcDailyTechnicalRepairWriteResult:
    """Recompute and atomically promote the explicit Gold repair range."""

    started_at = perf_counter()
    try:
        validate_silver_repair_batch(
            batch,
            expected_trade_dates=expected_trade_dates,
            registered_trade_dates=registered_trade_dates,
            max_indicator_recompute_dates=max_indicator_recompute_dates,
        )
    except ValueError as error:
        raise DcDailyTechnicalRepairValidationError(str(error)) from error

    expected = tuple(sorted(str(value) for value in expected_trade_dates))
    context_dates = _dates_between(
        expected,
        batch.context_start_trade_date,
        batch.indicator_recompute_end_trade_date,
    )
    source_dates = _dates_between(
        expected,
        batch.source_repair_start_trade_date,
        batch.source_repair_end_trade_date,
    )
    target_dates = _dates_between(
        expected,
        batch.indicator_recompute_start_trade_date,
        batch.indicator_recompute_end_trade_date,
    )
    source_paths = tuple(silver_dc_daily_path(lake_root_path, date_key) for date_key in context_dates)
    missing_paths = tuple(str(path) for path in source_paths if not path.exists())
    if missing_paths:
        raise FileNotFoundError(
            f"Missing Silver dc_daily repair context files: {missing_paths[:5]}"
        )

    target_paths = {
        date_key: gold_dc_daily_technical_path(lake_root_path, date_key)
        for date_key in target_dates
    }
    staging_paths: list[Path] = []
    partition_results: list[DcDailyTechnicalWriteResult] = []
    duckdb_started_at = perf_counter()
    staging_write_elapsed_ms = 0.0
    promote_elapsed_ms = 0.0

    try:
        with duckdb_resource.connect() as connection:
            source_schema = _schema_mismatches(
                connection,
                _read_paths(source_paths),
                SILVER_DC_DAILY_SCHEMA,
            )
            if source_schema["mismatch"]:
                raise DcDailyTechnicalRepairValidationError(
                    f"Silver dc_daily schema does not match contract: {source_schema}"
                )
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE dc_daily_technical_source AS "
                f"{_source_sql(tuple(zip(context_dates, source_paths)))}"
            )
            source_metrics = _validate_source(
                connection,
                context_dates,
                batch.indicator_recompute_end_trade_date,
            )

            current_revision = source_revision_for_silver_paths(
                connection,
                tuple(silver_dc_daily_path(lake_root_path, date_key) for date_key in source_dates),
            )
            if current_revision != batch.source_revision:
                raise DcDailyTechnicalRepairValidationError(
                    "Silver source_revision does not match the ready repair batch: "
                    f"expected={batch.source_revision}, actual={current_revision}"
                )

            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE dc_daily_technical_output AS "
                f"{_indicator_sql(None)}"
            )
            duckdb_elapsed_ms = (perf_counter() - duckdb_started_at) * 1000

            for date_key in target_dates:
                target_started_at = perf_counter()
                target_path = target_paths[date_key]
                relation = (
                    "(SELECT * FROM dc_daily_technical_output "
                    f"WHERE trade_date = DATE {duckdb_string(date_key)})"
                )
                target_source_row_count = int(
                    connection.execute(
                        f"SELECT count(*) FROM dc_daily_technical_source "
                        f"WHERE trade_date = DATE {duckdb_string(date_key)}"
                    ).fetchone()[0]
                    or 0
                )
                target_metrics = _validate_output_against_source(
                    connection,
                    relation,
                    target_trade_date=date_key,
                    expected_source_row_count=target_source_row_count,
                )

                target_path.parent.mkdir(parents=True, exist_ok=True)
                staging_path = target_path.with_name(
                    f"{target_path.name}.p7-repair-{uuid4().hex}.tmp"
                )
                staging_paths.append(staging_path)
                write_started_at = perf_counter()
                connection.execute(
                    f"COPY (SELECT * FROM {relation}) TO "
                    f"{duckdb_string(staging_path)} (FORMAT PARQUET)"
                )
                staging_write_elapsed_ms += (perf_counter() - write_started_at) * 1000

                staging_relation = read_parquet(staging_path, hive_partitioning=False)
                staging_schema = _schema_mismatches(
                    connection,
                    staging_relation,
                    GOLD_DC_DAILY_TECHNICAL_SCHEMA,
                )
                if staging_schema["mismatch"]:
                    raise DcDailyTechnicalRepairValidationError(
                        f"Gold technical staging schema does not match contract: {staging_schema}"
                    )
                staging_metrics = _validate_output_against_source(
                    connection,
                    staging_relation,
                    target_trade_date=date_key,
                    expected_source_row_count=target_source_row_count,
                )
                partition_results.append(
                    DcDailyTechnicalWriteResult(
                        trade_date=date_key,
                        target_path=target_path,
                        source_file_count=len(source_paths),
                        source_row_count=source_metrics["source_row_count"],
                        written_row_count=int(staging_metrics["row_count"]),
                        series_count=int(staging_metrics["series_count"]),
                        null_warmup_counts=dict(staging_metrics["null_warmup_counts"]),
                        duplicate_key_count=int(staging_metrics["duplicate_key_count"]),
                        input_rejection_count=source_metrics["input_rejection_count"],
                        duckdb_elapsed_ms=duckdb_elapsed_ms,
                        parquet_write_elapsed_ms=staging_write_elapsed_ms,
                        validation_elapsed_ms=(perf_counter() - target_started_at) * 1000,
                        total_elapsed_ms=(perf_counter() - target_started_at) * 1000,
                        peak_memory_bytes=_peak_memory_bytes(),
                        staging_path=staging_path,
                        skipped_existing=False,
                    )
                )

        promote_started_at = perf_counter()
        for staging_path, date_key in zip(staging_paths, target_dates):
            os.replace(staging_path, target_paths[date_key])
        promote_elapsed_ms = (perf_counter() - promote_started_at) * 1000
    except Exception:
        for staging_path in staging_paths:
            staging_path.unlink(missing_ok=True)
        raise

    return DcDailyTechnicalRepairWriteResult(
        upstream_batch_id=batch.upstream_batch_id,
        source_revision=batch.source_revision,
        source_repair_start_trade_date=batch.source_repair_start_trade_date,
        source_repair_end_trade_date=batch.source_repair_end_trade_date,
        indicator_recompute_start_trade_date=batch.indicator_recompute_start_trade_date,
        indicator_recompute_end_trade_date=batch.indicator_recompute_end_trade_date,
        context_start_trade_date=batch.context_start_trade_date,
        target_frontier_trade_date=batch.target_frontier_trade_date,
        source_file_count=len(source_paths),
        source_row_count=source_metrics["source_row_count"],
        rewritten_partition_count=len(partition_results),
        output_row_count=sum(item.written_row_count for item in partition_results),
        elapsed_ms=(perf_counter() - started_at) * 1000,
        duckdb_elapsed_ms=duckdb_elapsed_ms,
        staging_write_elapsed_ms=staging_write_elapsed_ms,
        promote_elapsed_ms=promote_elapsed_ms,
        peak_memory_bytes=max(
            (item.peak_memory_bytes for item in partition_results),
            default=_peak_memory_bytes(),
        ),
        partition_results=tuple(partition_results),
    )


def _dates_between(expected: Sequence[str], start: str, end: str) -> tuple[str, ...]:
    if start > end:
        raise DcDailyTechnicalRepairValidationError(
            f"Repair range start must not be later than end: {start} > {end}."
        )
    dates = tuple(date_key for date_key in expected if start <= date_key <= end)
    if not dates or dates[0] != start or dates[-1] != end:
        raise DcDailyTechnicalRepairValidationError(
            f"Repair range is outside expected calendar: {start}..{end}"
        )
    return dates


__all__ = [
    "MAX_GOLD_REPAIR_DATES",
    "DcDailyTechnicalRepairValidationError",
    "DcDailyTechnicalRepairWriteResult",
    "write_gold_dc_daily_technical_repair_batch",
]
