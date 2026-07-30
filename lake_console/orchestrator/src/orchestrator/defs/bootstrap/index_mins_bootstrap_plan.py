"""Read-only Bootstrap planning for the index minute lake.

P6 deliberately stops at source/target/budget evidence.  This module has no
lake promotion, Dagster event, dynamic-partition, or job execution path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter
from typing import Any

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    raw_index_mins_path,
    silver_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.index_mins import (
    IndexMinsActivePool,
    ProdIndexMinsSourceRangeProbe,
    ProdIndexMinsSourceReadiness,
    load_prod_index_mins_active_pool,
    probe_prod_index_mins_source_coverage_dates,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ASSET_FREQS,
    INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    INDEX_MINS_BOOTSTRAP_MAX_EXPECTED_DATES,
    INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_MS,
    INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_QUERIES,
    INDEX_MINS_BOOTSTRAP_MAX_TARGET_FILES,
    INDEX_MINS_HISTORY_START_DATE,
    INDEX_MINS_SOURCE_FREQS,
    INDEX_MINS_SILVER_FREQS,
)


_SAMPLE_LIMIT = 20
_RAW_ESTIMATED_BYTES_PER_ROW = 256
_SILVER_ESTIMATED_BYTES_PER_ROW = 320
_CODE_PATTERN = r"^[0-9A-Z]{1,12}\.[A-Z0-9]{2,8}$"


class IndexMinsBootstrapPlanError(ValueError):
    """Raised when the read-only Bootstrap plan cannot be trusted."""


@dataclass(frozen=True, slots=True)
class IndexMinsDatePlan:
    start_date: str
    end_date: str
    expected_trade_dates: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        sample = tuple(
            dict.fromkeys(
                (*self.expected_trade_dates[:3], *self.expected_trade_dates[-3:])
            )
        )
        return asdict(self) | {
            "expected_trade_dates": list(self.expected_trade_dates),
            "expected_date_count": len(self.expected_trade_dates),
            "expected_date_samples": list(sample),
        }


@dataclass(frozen=True, slots=True)
class IndexMinsTargetAudit:
    layer: str
    expected_file_count: int
    missing_count: int
    valid_existing_count: int
    invalid_existing_count: int
    scanned_file_count: int
    existing_bytes: int
    existing_row_count: int
    invalid_samples: tuple[Mapping[str, object], ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "invalid_samples": [dict(sample) for sample in self.invalid_samples]
        }


@dataclass(frozen=True, slots=True)
class IndexMinsDiskBudget:
    disk_free_bytes: int
    estimated_raw_bytes: int
    estimated_silver_bytes: int
    estimated_required_bytes: int
    safety_multiplier: float
    estimate_method: str
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexMinsBootstrapDryRunReport:
    generated_at: str
    lake_root: str
    date_plan: IndexMinsDatePlan
    active_pool_count: int
    active_pool_hash: str | None
    source_probe: ProdIndexMinsSourceRangeProbe | None
    source_probe_error: str | None
    source_probe_elapsed_ms: float
    source_readiness: tuple[ProdIndexMinsSourceReadiness, ...]
    target_audits: tuple[IndexMinsTargetAudit, ...]
    disk_budget: IndexMinsDiskBudget
    expected_raw_file_count: int
    expected_silver_file_count: int
    expected_file_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "date_plan": self.date_plan.to_dict(),
            "active_pool_count": self.active_pool_count,
            "active_pool_hash": self.active_pool_hash,
            "source_probe": self.source_probe.to_metadata()
            if self.source_probe is not None
            else None,
            "source_probe_error": self.source_probe_error,
            "source_probe_elapsed_ms": round(self.source_probe_elapsed_ms, 3),
            "source_readiness": [
                readiness.to_metadata() for readiness in self.source_readiness
            ],
            "target_audits": [audit.to_dict() for audit in self.target_audits],
            "disk_budget": self.disk_budget.to_dict(),
            "expected_raw_file_count": self.expected_raw_file_count,
            "expected_silver_file_count": self.expected_silver_file_count,
            "expected_file_count": self.expected_file_count,
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def build_date_plan(
    *,
    connection: Any,
    lake_root: Path,
    end_date: str | None = None,
) -> IndexMinsDatePlan:
    """Build the frozen SSE-open date plan from the Silver calendar."""

    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        raise IndexMinsBootstrapPlanError(f"missing Silver trade calendar: {calendar_path}")
    try:
        validation = connection.execute(
            f"""
            WITH calendar_rows AS (
              SELECT
                TRY_CAST(trade_date AS DATE) AS trade_date,
                CAST(exchange AS VARCHAR) AS exchange,
                TRY_CAST(is_open AS BOOLEAN) AS is_open
              FROM {read_parquet(calendar_path, hive_partitioning=False)}
            )
            SELECT
              count(*) FILTER (WHERE trade_date IS NULL),
              count(*) FILTER (
                WHERE exchange = 'SSE' AND is_open AND trade_date IS NULL
              ),
              count(*) FILTER (WHERE exchange = 'SSE' AND is_open)
                - count(DISTINCT trade_date) FILTER (
                    WHERE exchange = 'SSE' AND is_open
                  )
            FROM calendar_rows
            """
        ).fetchone()
        invalid_count = int(validation[0] or 0)
        invalid_open_count = int(validation[1] or 0)
        duplicate_open_count = int(validation[2] or 0)
        if invalid_count or invalid_open_count or duplicate_open_count:
            raise IndexMinsBootstrapPlanError(
                "trade calendar failed validation: "
                f"invalid_dates={invalid_count}, "
                f"invalid_open_dates={invalid_open_count}, "
                f"duplicate_open_dates={duplicate_open_count}."
            )
        rows = connection.execute(
            f"""
            SELECT CAST(TRY_CAST(trade_date AS DATE) AS VARCHAR) AS trade_date
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
              AND TRY_CAST(is_open AS BOOLEAN)
              AND TRY_CAST(trade_date AS DATE) >= DATE '{INDEX_MINS_HISTORY_START_DATE}'
            GROUP BY TRY_CAST(trade_date AS DATE)
            ORDER BY TRY_CAST(trade_date AS DATE)
            """
        ).fetchall()
    except IndexMinsBootstrapPlanError:
        raise
    except Exception as error:  # noqa: BLE001 - planner must fail closed.
        raise IndexMinsBootstrapPlanError(
            f"trade calendar scan failed: {type(error).__name__}"
        ) from error

    expected_dates = tuple(str(row[0]) for row in rows)
    if not expected_dates:
        raise IndexMinsBootstrapPlanError(
            f"no SSE open dates found from {INDEX_MINS_HISTORY_START_DATE}."
        )
    normalized_end = _normalize_end_date(end_date, expected_dates[-1])
    expected_dates = tuple(value for value in expected_dates if value <= normalized_end)
    if len(expected_dates) > INDEX_MINS_BOOTSTRAP_MAX_EXPECTED_DATES:
        raise IndexMinsBootstrapPlanError(
            "index_mins Bootstrap date budget exceeded: "
            f"count={len(expected_dates)}, max={INDEX_MINS_BOOTSTRAP_MAX_EXPECTED_DATES}."
        )
    if not expected_dates:
        raise IndexMinsBootstrapPlanError("Bootstrap end_date precedes the history start date.")
    return IndexMinsDatePlan(
        start_date=expected_dates[0],
        end_date=expected_dates[-1],
        expected_trade_dates=expected_dates,
        fingerprint=_date_plan_fingerprint(expected_dates),
    )


def run_dry_run(
    *,
    lake_root: Path,
    prod_postgres: ProdPostgresResource,
    duckdb_resource: DuckDBResource | None = None,
    end_date: str | None = None,
    active_pool_loader: Callable[..., IndexMinsActivePool] = load_prod_index_mins_active_pool,
    source_probe_runner: Callable[..., ProdIndexMinsSourceRangeProbe] = probe_prod_index_mins_source_coverage_dates,
) -> IndexMinsBootstrapDryRunReport:
    """Run the P6 read-only source, target, and budget audit."""

    started_at = perf_counter()
    duckdb_resource = duckdb_resource or DuckDBResource()
    with duckdb_resource.connect() as connection:
        date_plan = build_date_plan(
            connection=connection,
            lake_root=lake_root,
            end_date=end_date,
        )
        target_audits = _audit_targets(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=date_plan.expected_trade_dates,
        )

    active_pool: IndexMinsActivePool | None = None
    source_probe: ProdIndexMinsSourceRangeProbe | None = None
    source_probe_error: str | None = None
    source_probe_elapsed_ms = 0.0
    source_readiness: tuple[ProdIndexMinsSourceReadiness, ...] = ()
    stop_reason_codes: list[str] = []
    try:
        active_pool = active_pool_loader(prod_postgres=prod_postgres)
    except Exception as error:  # noqa: BLE001 - source audit is fail closed.
        stop_reason_codes.append("active_pool_query_failed")
        active_pool_error = error
    else:
        active_pool_error = None

    if active_pool is not None:
        source_probe_started_at = perf_counter()
        try:
            source_probe = source_probe_runner(
                prod_postgres=prod_postgres,
                trade_dates=date_plan.expected_trade_dates,
                effective_codes=active_pool.codes,
                max_query_count=INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_QUERIES,
                max_elapsed_ms=INDEX_MINS_BOOTSTRAP_MAX_SOURCE_PROBE_MS,
            )
            source_readiness = source_probe.readiness_by_date
        except Exception as error:  # noqa: BLE001 - source audit is fail closed.
            stop_reason_codes.append(_source_probe_reason(error))
            source_probe_error = f"{type(error).__name__}: {error}"
        finally:
            source_probe_elapsed_ms = (perf_counter() - source_probe_started_at) * 1000

    if source_probe is not None:
        failed_source_dates = tuple(
            readiness.trade_date
            for readiness in source_readiness
            if not readiness.ready
        )
        if not source_probe.ready or failed_source_dates:
            stop_reason_codes.append("source_coverage_not_ready")
        if len(source_readiness) != len(date_plan.expected_trade_dates):
            stop_reason_codes.append("source_date_count_mismatch")

    if any(audit.invalid_existing_count for audit in target_audits):
        stop_reason_codes.append("invalid_existing_target")

    disk_budget = _build_disk_budget(
        lake_root=lake_root,
        date_plan=date_plan,
        source_readiness=source_readiness,
        target_audits=target_audits,
    )
    if not disk_budget.passed:
        stop_reason_codes.append("insufficient_disk_space")

    if active_pool_error is not None and "active_pool_query_failed" not in stop_reason_codes:
        stop_reason_codes.append("active_pool_query_failed")

    return IndexMinsBootstrapDryRunReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        date_plan=date_plan,
        active_pool_count=active_pool.code_count if active_pool else 0,
        active_pool_hash=active_pool.code_set_hash if active_pool else None,
        source_probe=source_probe,
        source_probe_error=source_probe_error,
        source_probe_elapsed_ms=source_probe_elapsed_ms,
        source_readiness=source_readiness,
        target_audits=target_audits,
        disk_budget=disk_budget,
        expected_raw_file_count=len(date_plan.expected_trade_dates) * len(INDEX_MINS_ASSET_FREQS),
        expected_silver_file_count=len(date_plan.expected_trade_dates) * len(INDEX_MINS_SILVER_FREQS),
        expected_file_count=len(date_plan.expected_trade_dates)
        * (len(INDEX_MINS_ASSET_FREQS) + len(INDEX_MINS_SILVER_FREQS)),
        should_stop=bool(stop_reason_codes),
        stop_reason_codes=tuple(dict.fromkeys(stop_reason_codes)),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def write_report(report: IndexMinsBootstrapDryRunReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _audit_targets(
    *,
    connection: Any,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[IndexMinsTargetAudit, ...]:
    specs = {
        "raw": tuple(
            (source_freq, trade_date, raw_index_mins_path(lake_root, source_freq, trade_date))
            for trade_date in expected_trade_dates
            for source_freq in INDEX_MINS_SOURCE_FREQS
        ),
        "silver": tuple(
            (f"{frequency}min", trade_date, silver_index_mins_path(lake_root, frequency, trade_date))
            for trade_date in expected_trade_dates
            for frequency in INDEX_MINS_SILVER_FREQS
        ),
    }
    file_count = sum(len(values) for values in specs.values())
    if file_count > INDEX_MINS_BOOTSTRAP_MAX_TARGET_FILES:
        raise IndexMinsBootstrapPlanError(
            "index_mins target audit file budget exceeded: "
            f"count={file_count}, max={INDEX_MINS_BOOTSTRAP_MAX_TARGET_FILES}."
        )
    audits: list[IndexMinsTargetAudit] = []
    for layer, entries in specs.items():
        audits.append(
            _audit_target_layer(
                connection=connection,
                entries=entries,
                layer=layer,
                expected_schema=(
                    RAW_INDEX_MINS_SCHEMA if layer == "raw" else SILVER_INDEX_MINS_SCHEMA
                ),
            )
        )
    return tuple(audits)


def _audit_target_layer(
    *,
    connection: Any,
    entries: Sequence[tuple[str, str, Path]],
    layer: str,
    expected_schema: Sequence[Any],
) -> IndexMinsTargetAudit:
    started_at = perf_counter()
    existing = tuple(entry for entry in entries if entry[2].exists())
    missing_count = sum(not entry[2].exists() for entry in entries)
    expected_columns = tuple((str(column.name), str(column.type).upper()) for column in expected_schema)
    invalid_samples: list[Mapping[str, object]] = []
    schema_valid = _schema_valid_paths(
        connection=connection,
        entries=existing,
        expected_columns=expected_columns,
        layer=layer,
        invalid_samples=invalid_samples,
    )

    valid_existing_count = 0
    existing_row_count = 0
    existing_bytes = sum(path.stat().st_size for _, _, path in existing)
    if schema_valid:
        paths = [str(path) for _, _, path in schema_valid]
        metrics = connection.execute(
            """
            SELECT
              filename,
              count(*) AS row_count,
              count(*) FILTER (
                WHERE ts_code IS NULL
                   OR NOT regexp_matches(upper(trim(CAST(ts_code AS VARCHAR))), ?)
                   OR freq IS NULL
                   OR CAST(freq AS VARCHAR) <> regexp_extract(filename, 'freq=([^/]+)', 1)
                   OR trade_time IS NULL
                   OR CAST(trade_time AS DATE) <> CAST(regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE)
                   OR open IS NULL OR close IS NULL OR high IS NULL OR low IS NULL
                   OR NOT isfinite(CAST(open AS DOUBLE))
                   OR NOT isfinite(CAST(close AS DOUBLE))
                   OR NOT isfinite(CAST(high AS DOUBLE))
                   OR NOT isfinite(CAST(low AS DOUBLE))
                   OR open <= 0 OR close <= 0 OR high <= 0 OR low <= 0
                   OR high < low OR open < low OR open > high
                   OR close < low OR close > high
                   OR vol IS NULL OR amount IS NULL
                   OR NOT isfinite(CAST(vol AS DOUBLE)) OR NOT isfinite(CAST(amount AS DOUBLE))
                   OR vol < 0 OR amount < 0
              ) AS invalid_count,
              count(*) - count(DISTINCT (ts_code, freq, trade_time)) AS duplicate_count
            FROM read_parquet(?, filename=true, hive_partitioning=false)
            GROUP BY filename
            """,
            [_CODE_PATTERN, paths],
        ).fetchall()
        metrics_by_path = {str(Path(str(row[0])).resolve()): row[1:] for row in metrics}
        for source_freq, trade_date, path in schema_valid:
            row_count, invalid_count, duplicate_count = metrics_by_path.get(
                str(path.resolve()), (0, 0, 0)
            )
            row_count = int(row_count or 0)
            invalid_count = int(invalid_count or 0)
            duplicate_count = int(duplicate_count or 0)
            existing_row_count += row_count
            if row_count > 0 and invalid_count == 0 and duplicate_count == 0:
                valid_existing_count += 1
            elif len(invalid_samples) < _SAMPLE_LIMIT:
                invalid_samples.append(
                    {
                        "layer": layer,
                        "trade_date": trade_date,
                        "source_freq": source_freq,
                        "reason_code": "core_contract_failed",
                        "invalid_row_count": invalid_count,
                        "duplicate_key_count": duplicate_count,
                        "path": str(path),
                    }
                )
    return IndexMinsTargetAudit(
        layer=layer,
        expected_file_count=len(entries),
        missing_count=missing_count,
        valid_existing_count=valid_existing_count,
        invalid_existing_count=len(existing) - valid_existing_count,
        scanned_file_count=len(existing),
        existing_bytes=existing_bytes,
        existing_row_count=existing_row_count,
        invalid_samples=tuple(invalid_samples[:_SAMPLE_LIMIT]),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def _schema_valid_paths(
    *,
    connection: Any,
    entries: Sequence[tuple[str, str, Path]],
    expected_columns: tuple[tuple[str, str], ...],
    layer: str,
    invalid_samples: list[Mapping[str, object]],
) -> list[tuple[str, str, Path]]:
    if not entries:
        return []
    paths = [str(path) for _, _, path in entries]
    try:
        observed = tuple(
            (str(row[0]), str(row[1]).upper().split("(", 1)[0])
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [paths],
            ).fetchall()
        )
    except Exception:
        observed = ()
    if observed == expected_columns:
        return list(entries)

    valid: list[tuple[str, str, Path]] = []
    for source_freq, trade_date, path in entries:
        try:
            single_observed = tuple(
                (str(row[0]), str(row[1]).upper().split("(", 1)[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            )
        except Exception as error:  # noqa: BLE001 - corrupt target is invalid.
            reason = f"parquet_unreadable:{type(error).__name__}"
            single_observed = ()
        else:
            reason = "schema_mismatch" if single_observed != expected_columns else ""
        if reason:
            if len(invalid_samples) < _SAMPLE_LIMIT:
                invalid_samples.append(
                    {
                        "layer": layer,
                        "trade_date": trade_date,
                        "source_freq": source_freq,
                        "reason_code": reason,
                        "path": str(path),
                    }
                )
        else:
            valid.append((source_freq, trade_date, path))
    return valid


def _build_disk_budget(
    *,
    lake_root: Path,
    date_plan: IndexMinsDatePlan,
    source_readiness: Sequence[ProdIndexMinsSourceReadiness],
    target_audits: Sequence[IndexMinsTargetAudit],
) -> IndexMinsDiskBudget:
    usage = shutil.disk_usage(lake_root)
    source_rows_by_freq = {
        source_freq: sum(
            next(
                (
                    coverage.source_row_count
                    for coverage in readiness.frequency_coverages
                    if coverage.source_freq == source_freq
                ),
                0,
            )
            for readiness in source_readiness
        )
        for source_freq in INDEX_MINS_SOURCE_FREQS
    }
    existing_rows = {
        audit.layer: audit.existing_row_count for audit in target_audits
    }
    existing_bytes = {audit.layer: audit.existing_bytes for audit in target_audits}
    raw_missing_rows = sum(
        source_rows_by_freq.values()
    ) - min(existing_rows.get("raw", 0), sum(source_rows_by_freq.values()))
    silver_missing_rows = (
        sum(source_rows_by_freq.values()) * 2
        - min(existing_rows.get("silver", 0), sum(source_rows_by_freq.values()) * 2)
    )
    estimated_raw_bytes = max(
        raw_missing_rows * _RAW_ESTIMATED_BYTES_PER_ROW,
        0,
    )
    estimated_silver_bytes = max(
        silver_missing_rows * _SILVER_ESTIMATED_BYTES_PER_ROW,
        0,
    )
    # Existing files provide a real compression sample; otherwise the fixed
    # row-size bound is deliberately conservative and is reported as such.
    estimate_method = (
        "existing_file_row_size_plus_conservative_row_bound"
        if any(existing_bytes.values())
        else "conservative_schema_row_bound"
    )
    required = int(
        (estimated_raw_bytes + estimated_silver_bytes)
        * INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER
    )
    return IndexMinsDiskBudget(
        disk_free_bytes=usage.free,
        estimated_raw_bytes=estimated_raw_bytes,
        estimated_silver_bytes=estimated_silver_bytes,
        estimated_required_bytes=required,
        safety_multiplier=INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
        estimate_method=estimate_method,
        passed=usage.free >= required,
    )


def _normalize_end_date(value: str | None, calendar_end: str) -> str:
    today = date.today().isoformat()
    normalized = min(calendar_end, today) if value is None else str(value).strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as error:
        raise IndexMinsBootstrapPlanError(
            f"end_date must be YYYY-MM-DD: {value!r}"
        ) from error
    if normalized > calendar_end:
        raise IndexMinsBootstrapPlanError(
            f"end_date is beyond the calendar frontier: {normalized} > {calendar_end}."
        )
    if normalized > today:
        raise IndexMinsBootstrapPlanError(
            f"end_date cannot be in the future: {normalized} > {today}."
        )
    if parsed < date.fromisoformat(INDEX_MINS_HISTORY_START_DATE):
        raise IndexMinsBootstrapPlanError("end_date precedes the index_mins history start date.")
    return normalized


def _date_plan_fingerprint(dates: Sequence[str]) -> str:
    return hashlib.sha256(
        "\n".join(("index_mins", INDEX_MINS_HISTORY_START_DATE, *dates)).encode("utf-8")
    ).hexdigest()


def _source_probe_reason(error: Exception) -> str:
    message = str(error).lower()
    if "query budget" in message:
        return "source_probe_query_budget_exceeded"
    if "time budget" in message:
        return "source_probe_time_budget_exceeded"
    return "source_probe_failed"


__all__ = [
    "IndexMinsBootstrapDryRunReport",
    "IndexMinsBootstrapPlanError",
    "IndexMinsDatePlan",
    "IndexMinsDiskBudget",
    "IndexMinsTargetAudit",
    "build_date_plan",
    "run_dry_run",
    "write_report",
]
