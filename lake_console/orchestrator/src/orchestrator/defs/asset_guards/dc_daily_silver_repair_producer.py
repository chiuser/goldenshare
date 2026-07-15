"""Bounded, source-backed repair producer for ``silver_dc_daily``.

The producer rebuilds an explicit source-date range from Raw files, stages all
candidate Silver outputs on one DuckDB connection, compares them with the old
Silver partitions, and only then promotes changed files.  It produces the
validated ``SilverRepairBatch`` consumed by a future Gold repair job.  It does
not define Dagster assets, inspect event history, or write Dagster metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import os

from orchestrator.defs.asset_guards.dc_daily_silver_repair import (
    build_dc_daily_silver_repair_batch,
)
from orchestrator.defs.assets.dc_board_silver import (
    DcBoardSilverStagingResult,
    DcBoardSilverWriteResult,
    stage_silver_dc_daily_partition_with_connection,
)
from orchestrator.defs.duckdb_sql import (
    describe_parquet_query,
    duckdb_string,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    silver_dc_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import SILVER_DC_DAILY_SCHEMA
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
    DC_DAILY_SILVER_REPAIR_MAX_SOURCE_DATES,
)
from orchestrator.defs.run_contracts.silver_repair import (
    SilverRepairBatch,
    hash_affected_series,
    normalize_expected_trade_dates,
    normalize_trade_date,
    validate_silver_repair_batch,
)


SILVER_DC_DAILY_SOURCE_REVISION_PREFIX = "silver_dc_daily:v1:"
MAX_AFFECTED_SERIES = 100_000


class DcDailySilverRepairValidationError(ValueError):
    """Raised when a bounded Silver repair cannot be safely produced."""


@dataclass(frozen=True, slots=True)
class DcDailySilverRepairResult:
    """Auditable result of one bounded source repair attempt."""

    producer_run_id: str
    batch: SilverRepairBatch | None
    source_revision: str
    source_repair_start_trade_date: str
    source_repair_end_trade_date: str
    indicator_recompute_start_trade_date: str
    indicator_recompute_end_trade_date: str
    context_start_trade_date: str
    target_frontier_trade_date: str
    source_row_count: int
    output_row_count: int
    staged_partition_count: int
    rewritten_partition_count: int
    affected_series_count: int
    affected_series_hash: str | None
    no_op: bool
    elapsed_ms: float
    partition_results: tuple[DcBoardSilverWriteResult, ...]

    def to_metadata(self) -> dict[str, object]:
        return {
            "source_asset": "silver_dc_daily",
            "producer_run_id": self.producer_run_id,
            "source_revision": self.source_revision,
            "source_repair_start_trade_date": self.source_repair_start_trade_date,
            "source_repair_end_trade_date": self.source_repair_end_trade_date,
            "indicator_recompute_start_trade_date": self.indicator_recompute_start_trade_date,
            "indicator_recompute_end_trade_date": self.indicator_recompute_end_trade_date,
            "context_start_trade_date": self.context_start_trade_date,
            "target_frontier_trade_date": self.target_frontier_trade_date,
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "staged_partition_count": self.staged_partition_count,
            "rewritten_partition_count": self.rewritten_partition_count,
            "affected_series_count": self.affected_series_count,
            "affected_series_hash": self.affected_series_hash,
            "no_op": self.no_op,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "repair_batch": self.batch.to_payload() if self.batch else None,
            "write_mode": "duckdb_bounded_stage_compare_atomic_replace",
        }


def produce_dc_daily_silver_repair_batch(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    producer_run_id: str,
    source_repair_start_trade_date: str,
    source_repair_end_trade_date: str,
    indicator_recompute_end_trade_date: str,
    target_frontier_trade_date: str,
    expected_trade_dates: Sequence[object],
    registered_trade_dates: Sequence[object],
    context_start_trade_date: str | None = None,
    max_source_repair_dates: int = DC_DAILY_SILVER_REPAIR_MAX_SOURCE_DATES,
    max_indicator_recompute_dates: int = DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES,
) -> DcDailySilverRepairResult:
    """Rebuild a bounded Silver range and return a ready repair batch.

    ``indicator_recompute_end_trade_date`` and ``target_frontier_trade_date``
    are explicit inputs.  The producer never infers them from event history or
    file mtimes.  The Gold consumer is expected to recompute from the source
    repair start through the explicit indicator end, using the context start
    as its earliest input date.
    """

    started_at = perf_counter()
    run_id = _require_text(producer_run_id, "producer_run_id")
    expected = normalize_expected_trade_dates(expected_trade_dates)
    registered = set(normalize_expected_trade_dates(registered_trade_dates))
    source_start = normalize_trade_date(
        source_repair_start_trade_date,
        field_name="source_repair_start_trade_date",
    )
    source_end = normalize_trade_date(
        source_repair_end_trade_date,
        field_name="source_repair_end_trade_date",
    )
    indicator_start = source_start
    indicator_end = normalize_trade_date(
        indicator_recompute_end_trade_date,
        field_name="indicator_recompute_end_trade_date",
    )
    context_start = normalize_trade_date(
        context_start_trade_date or expected[0],
        field_name="context_start_trade_date",
    )
    target_frontier = normalize_trade_date(
        target_frontier_trade_date,
        field_name="target_frontier_trade_date",
    )
    if max_source_repair_dates <= 0 or max_indicator_recompute_dates <= 0:
        raise DcDailySilverRepairValidationError(
            "Silver repair budgets must be positive."
        )
    if source_end > indicator_end:
        raise DcDailySilverRepairValidationError(
            "Indicator recompute range must cover the source repair end."
        )
    if target_frontier not in expected:
        raise DcDailySilverRepairValidationError(
            f"Target frontier is outside expected calendar: {target_frontier}"
        )
    source_dates = _dates_between(expected, source_start, source_end)
    indicator_dates = _dates_between(expected, indicator_start, indicator_end)
    if not source_dates:
        raise DcDailySilverRepairValidationError(
            "Silver source repair range contains no expected trade dates."
        )
    if not indicator_dates:
        raise DcDailySilverRepairValidationError(
            "Silver indicator recompute range contains no expected trade dates."
        )
    if len(source_dates) > max_source_repair_dates:
        raise DcDailySilverRepairValidationError(
            "Silver source repair range exceeds bounded budget: "
            f"count={len(source_dates)}, max={max_source_repair_dates}."
        )
    if len(indicator_dates) > max_indicator_recompute_dates:
        raise DcDailySilverRepairValidationError(
            "Silver indicator recompute range exceeds bounded budget: "
            f"count={len(indicator_dates)}, max={max_indicator_recompute_dates}."
        )
    if context_start > indicator_start:
        raise DcDailySilverRepairValidationError(
            "context_start_trade_date must not be later than indicator recompute start."
        )
    if indicator_end > target_frontier:
        raise DcDailySilverRepairValidationError(
            "target_frontier_trade_date must cover indicator recompute end."
        )
    required_dates = _dates_between(expected, context_start, indicator_end)
    missing_expected = tuple(date_key for date_key in required_dates if date_key not in expected)
    if missing_expected:
        raise DcDailySilverRepairValidationError(
            f"Required Silver context dates are outside expected calendar: {missing_expected[:5]}"
        )
    missing_registered = tuple(date_key for date_key in indicator_dates if date_key not in registered)
    if missing_registered:
        raise DcDailySilverRepairValidationError(
            "Indicator recompute range contains unregistered dates: "
            f"{missing_registered[:5]}"
        )
    if target_frontier not in registered:
        raise DcDailySilverRepairValidationError(
            f"Target frontier is not a registered trade date: {target_frontier}"
        )

    calendar_path = silver_trade_calendar_path(lake_root_path)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing Silver trade calendar: {calendar_path}")
    missing_raw = tuple(
        str(raw_dc_daily_path(lake_root_path, date_key))
        for date_key in source_dates
        if not raw_dc_daily_path(lake_root_path, date_key).exists()
    )
    if missing_raw:
        raise FileNotFoundError(f"Missing Raw dc_daily repair inputs: {missing_raw[:5]}")
    source_date_set = set(source_dates)
    missing_context = tuple(
        str(silver_dc_daily_path(lake_root_path, date_key))
        for date_key in required_dates
        if date_key not in source_date_set
        and not silver_dc_daily_path(lake_root_path, date_key).exists()
    )
    if missing_context:
        raise FileNotFoundError(
            "Missing Silver context inputs outside source repair range: "
            f"{missing_context[:5]}"
        )

    staged: list[DcBoardSilverStagingResult] = []
    try:
        with duckdb_resource.connect() as connection:
            for date_key in source_dates:
                staged.append(
                    stage_silver_dc_daily_partition_with_connection(
                        lake_root_path=lake_root_path,
                        connection=connection,
                        partition_key=date_key,
                    )
                )

            source_revision = _source_revision(connection, tuple(item.staging_path for item in staged))
            changed_series: set[str] = set()
            changed_staged: list[DcBoardSilverStagingResult] = []
            for item in staged:
                changed = _changed_series_for_partition(
                    connection,
                    item.staging_path,
                    item.result.target_file_path,
                )
                if changed:
                    changed_series.update(changed)
                    changed_staged.append(item)

            if len(changed_series) > MAX_AFFECTED_SERIES:
                raise DcDailySilverRepairValidationError(
                    "Affected Silver series exceed bounded metadata budget: "
                    f"count={len(changed_series)}, max={MAX_AFFECTED_SERIES}."
                )
            no_op = not changed_staged
            affected_hash = hash_affected_series(tuple(sorted(changed_series))) if changed_series else None
            batch = None
            if not no_op:
                if affected_hash is None:
                    raise DcDailySilverRepairValidationError(
                        "Changed Silver partitions must produce affected series hash."
                    )
                batch = build_dc_daily_silver_repair_batch(
                    producer_run_id=run_id,
                    source_revision=source_revision,
                    source_repair_start_trade_date=source_start,
                    source_repair_end_trade_date=source_end,
                    indicator_recompute_start_trade_date=indicator_start,
                    indicator_recompute_end_trade_date=indicator_end,
                    context_start_trade_date=context_start,
                    target_frontier_trade_date=target_frontier,
                    affected_date_count=len(source_dates),
                    affected_series_count=len(changed_series),
                    affected_series_hash=affected_hash,
                    truncated=False,
                    selected_partition_count=len(indicator_dates),
                    expected_trade_dates=expected,
                    registered_trade_dates=registered,
                )
                validate_silver_repair_batch(
                    batch,
                    expected_trade_dates=expected,
                    registered_trade_dates=registered,
                    max_indicator_recompute_dates=max_indicator_recompute_dates,
                )

            changed_paths = {item.staging_path for item in changed_staged}
            for item in staged:
                if item.staging_path in changed_paths:
                    os.replace(item.staging_path, item.result.target_file_path)
                elif item.staging_path.exists():
                    item.staging_path.unlink()

            return DcDailySilverRepairResult(
                producer_run_id=run_id,
                batch=batch,
                source_revision=source_revision,
                source_repair_start_trade_date=source_start,
                source_repair_end_trade_date=source_end,
                indicator_recompute_start_trade_date=indicator_start,
                indicator_recompute_end_trade_date=indicator_end,
                context_start_trade_date=context_start,
                target_frontier_trade_date=target_frontier,
                source_row_count=sum(item.result.source_row_count for item in staged),
                output_row_count=sum(item.result.output_row_count for item in staged),
                staged_partition_count=len(staged),
                rewritten_partition_count=len(changed_staged),
                affected_series_count=len(changed_series),
                affected_series_hash=affected_hash,
                no_op=no_op,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                partition_results=tuple(item.result for item in staged),
            )
    except Exception:
        _cleanup_staging(staged)
        raise


def _source_revision(connection, staging_paths: tuple[Path, ...]) -> str:
    relation = _read_paths(staging_paths)
    digest = connection.execute(
        f"""
        SELECT sha256(
          concat(
            {duckdb_string(SILVER_DC_DAILY_SOURCE_REVISION_PREFIX)},
            coalesce(
              string_agg(
                concat_ws(
                  chr(31),
                  coalesce(CAST(ts_code AS VARCHAR), '<NULL>'),
                  coalesce(strftime(CAST(trade_date AS DATE), '%Y-%m-%d'), '<NULL>'),
                  coalesce(CAST(category AS VARCHAR), '<NULL>'),
                  coalesce(CAST(close AS VARCHAR), '<NULL>'),
                  coalesce(CAST(high AS VARCHAR), '<NULL>'),
                  coalesce(CAST(low AS VARCHAR), '<NULL>')
                ),
                chr(10) ORDER BY ts_code, trade_date, category, close, high, low
              ),
              ''
            )
          )
        )
        FROM {relation}
        """
    ).fetchone()[0]
    return f"{SILVER_DC_DAILY_SOURCE_REVISION_PREFIX}{digest}"


def _changed_series_for_partition(connection, staging_path: Path, target_path: Path) -> set[str]:
    if not target_path.exists():
        rows = connection.execute(
            f"""
            SELECT DISTINCT concat_ws('|', CAST(ts_code AS VARCHAR), CAST(category AS VARCHAR))
            FROM {_read_paths((staging_path,))}
            """
        ).fetchall()
        return {str(row[0]) for row in rows}

    try:
        observed = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(describe_parquet_query(target_path)).fetchall()
        )
    except Exception as error:
        raise DcDailySilverRepairValidationError(
            f"Existing Silver dc_daily target schema is invalid: {target_path}"
        ) from error
    expected = tuple((str(column.name), str(column.type).upper()) for column in SILVER_DC_DAILY_SCHEMA)
    if observed != expected:
        raise DcDailySilverRepairValidationError(
            f"Existing Silver dc_daily target schema is invalid: {target_path}"
        )
    new_relation = _read_paths((staging_path,))
    old_relation = _read_paths((target_path,))
    rows = connection.execute(
        f"""
        WITH new_values AS (
          SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                 CAST(trade_date AS DATE) AS trade_date,
                 CAST(category AS VARCHAR) AS category,
                 CAST(close AS DOUBLE) AS close,
                 CAST(high AS DOUBLE) AS high,
                 CAST(low AS DOUBLE) AS low
          FROM {new_relation}
        ), old_values AS (
          SELECT CAST(ts_code AS VARCHAR) AS ts_code,
                 CAST(trade_date AS DATE) AS trade_date,
                 CAST(category AS VARCHAR) AS category,
                 CAST(close AS DOUBLE) AS close,
                 CAST(high AS DOUBLE) AS high,
                 CAST(low AS DOUBLE) AS low
          FROM {old_relation}
        ), changed AS (
          SELECT * FROM new_values
          EXCEPT
          SELECT * FROM old_values
          UNION
          SELECT * FROM old_values
          EXCEPT
          SELECT * FROM new_values
        )
        SELECT DISTINCT concat_ws('|', ts_code, category)
        FROM changed
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _read_paths(paths: tuple[Path, ...]) -> str:
    if not paths:
        raise ValueError("At least one parquet path is required.")
    quoted = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{quoted}], hive_partitioning=false)"


def _dates_between(expected: Sequence[str], start: str, end: str) -> tuple[str, ...]:
    if start > end:
        raise DcDailySilverRepairValidationError(
            f"Repair range start must not be later than end: {start} > {end}."
        )
    dates = tuple(date_key for date_key in expected if start <= date_key <= end)
    required = {start, end}
    missing = tuple(sorted(required - set(expected)))
    if missing:
        raise DcDailySilverRepairValidationError(
            f"Repair range dates are outside expected calendar: {missing}"
        )
    return dates


def _cleanup_staging(staged: Sequence[DcBoardSilverStagingResult]) -> None:
    for item in staged:
        if item.staging_path.exists():
            item.staging_path.unlink()


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DcDailySilverRepairValidationError(f"{field_name} must be non-empty text.")
    return value.strip()


__all__ = [
    "DC_DAILY_SILVER_REPAIR_MAX_INDICATOR_RECOMPUTE_DATES",
    "DC_DAILY_SILVER_REPAIR_MAX_SOURCE_DATES",
    "DcDailySilverRepairResult",
    "DcDailySilverRepairValidationError",
    "SILVER_DC_DAILY_SOURCE_REVISION_PREFIX",
    "produce_dc_daily_silver_repair_batch",
]
