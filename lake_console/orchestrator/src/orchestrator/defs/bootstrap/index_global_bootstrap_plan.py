"""Read-only Bootstrap planning for the international index lake.

This module freezes the natural-date plan and audits existing Raw/Silver target
files. It deliberately has no source-fetch, lake-promotion, or Dagster event
write path; those operations are separate approval gates after this report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.paths import raw_index_global_path, silver_index_global_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_START_DATE,
    INDEX_GLOBAL_EXPECTED_CODES,
    INDEX_GLOBAL_NORMAL_PHASES,
)


_SAMPLE_LIMIT = 20


class IndexGlobalBootstrapPlanError(ValueError):
    """Raised when a read-only Bootstrap plan cannot be trusted."""


@dataclass(frozen=True, slots=True)
class IndexGlobalDatePlan:
    start_date: str
    end_date: str
    expected_natural_dates: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "expected_natural_dates": list(self.expected_natural_dates)
        }


@dataclass(frozen=True, slots=True)
class IndexGlobalTargetFileStatus:
    layer: str
    trade_date: str
    path: str
    status: str
    reason_code: str
    row_count: int
    file_size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexGlobalTargetLayerAudit:
    layer: str
    expected_file_count: int
    missing_count: int
    valid_existing_count: int
    invalid_existing_count: int
    existing_bytes: int
    scan_elapsed_ms: float
    invalid_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "invalid_samples": [dict(sample) for sample in self.invalid_samples]
        }


@dataclass(frozen=True, slots=True)
class IndexGlobalBootstrapDryRunReport:
    generated_at: str
    lake_root: str
    date_plan: IndexGlobalDatePlan
    source_probe: str
    phase_count: int
    estimated_source_request_count: int
    expected_raw_file_count: int
    expected_silver_file_count: int
    target_audits: tuple[IndexGlobalTargetLayerAudit, ...]
    target_files: tuple[IndexGlobalTargetFileStatus, ...]
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "date_plan": self.date_plan.to_dict(),
            "source_probe": self.source_probe,
            "phase_count": self.phase_count,
            "estimated_source_request_count": self.estimated_source_request_count,
            "expected_raw_file_count": self.expected_raw_file_count,
            "expected_silver_file_count": self.expected_silver_file_count,
            "target_audits": [audit.to_dict() for audit in self.target_audits],
            "target_files": [status.to_dict() for status in self.target_files],
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def _normalize_date(value: str, *, field_name: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise IndexGlobalBootstrapPlanError(
            f"{field_name} must be YYYY-MM-DD: {value!r}"
        ) from exc


def _date_plan_fingerprint(dates: Sequence[str]) -> str:
    payload = "\n".join(("index_global", GLOBAL_INDEX_START_DATE, *dates))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_date_plan(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> IndexGlobalDatePlan:
    """Build the fixed natural-date Bootstrap plan without reading a calendar."""

    normalized_start = _normalize_date(
        start_date or GLOBAL_INDEX_START_DATE,
        field_name="start_date",
    )
    normalized_end = _normalize_date(
        end_date or date.today().isoformat(),
        field_name="end_date",
    )
    if normalized_start < GLOBAL_INDEX_START_DATE:
        raise IndexGlobalBootstrapPlanError(
            f"start_date cannot precede {GLOBAL_INDEX_START_DATE}: {normalized_start}"
        )
    if normalized_end > date.today().isoformat():
        raise IndexGlobalBootstrapPlanError(
            f"end_date cannot be in the future: {normalized_end}"
        )
    if normalized_start > normalized_end:
        raise IndexGlobalBootstrapPlanError(
            f"start_date must not be after end_date: {normalized_start} > {normalized_end}"
        )

    first = date.fromisoformat(normalized_start)
    last = date.fromisoformat(normalized_end)
    natural_dates = tuple(
        (first.fromordinal(day).isoformat() for day in range(first.toordinal(), last.toordinal() + 1))
    )
    return IndexGlobalDatePlan(
        start_date=normalized_start,
        end_date=normalized_end,
        expected_natural_dates=natural_dates,
        fingerprint=_date_plan_fingerprint(natural_dates),
    )


def _schema_contract(schema: Sequence[Any]) -> tuple[tuple[str, str], ...]:
    return tuple((str(column.name), str(column.type).upper()) for column in schema)


def _describe_files(
    connection: Any,
    paths: Sequence[Path],
    *,
    schema: Sequence[Any],
) -> dict[Path, tuple[str, str]]:
    """Validate all existing files with one batch schema read when possible."""

    expected = _schema_contract(schema)
    if not paths:
        return {}
    path_values = [str(path) for path in paths]
    try:
        observed = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                [path_values],
            ).fetchall()
        )
    except Exception:
        observed = ()
    if observed == expected:
        return {path: expected for path in paths}

    result: dict[Path, tuple[str, str]] = {}
    for path in paths:
        try:
            result[path] = tuple(
                    (str(row[0]), str(row[1]).upper())
                    for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                    [[str(path)]],
                ).fetchall()
            )
        except Exception:
            result[path] = ()
    return result


def _target_row_query(*, layer: str, schema: Sequence[Any]) -> str:
    partition_from_path = (
        "replace(regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1), '-', '')"
        if layer == "raw"
        else "CAST(regexp_extract(filename, 'trade_date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1) AS DATE)"
    )
    if layer == "raw":
        date_invalid = (
            "trade_date IS NULL OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') "
            f"<> {partition_from_path}"
        )
    else:
        date_invalid = f"trade_date IS NULL OR trade_date <> {partition_from_path}"
    numeric_predicate = " OR ".join(
        f'("{column.name}" IS NOT NULL AND NOT isfinite("{column.name}"))'
        for column in schema[2:]
    )
    expected_codes = ", ".join(f"'{code}'" for code in INDEX_GLOBAL_EXPECTED_CODES)
    return f"""
        SELECT
          filename,
          count(*) AS row_count,
          count(*) FILTER (WHERE {date_invalid}) AS invalid_scope_count,
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
              OR trim(CAST(ts_code AS VARCHAR)) NOT IN ({expected_codes})
          ) AS invalid_identity_count,
          count(*) - count(DISTINCT (ts_code, trade_date)) AS duplicate_count,
          count(*) FILTER (WHERE {numeric_predicate}) AS non_finite_count
        FROM read_parquet(?, filename=true, hive_partitioning=false)
        GROUP BY filename
    """


def _audit_layer(
    *,
    connection: Any,
    lake_root: Path,
    dates: Sequence[str],
    layer: str,
) -> tuple[IndexGlobalTargetLayerAudit, tuple[IndexGlobalTargetFileStatus, ...]]:
    started = perf_counter()
    path_builder = raw_index_global_path if layer == "raw" else silver_index_global_path
    schema = RAW_INDEX_GLOBAL_SCHEMA if layer == "raw" else SILVER_INDEX_GLOBAL_SCHEMA
    expected = _schema_contract(schema)
    statuses: dict[str, IndexGlobalTargetFileStatus] = {}
    existing_paths: list[Path] = []
    for trade_date in dates:
        path = path_builder(lake_root, trade_date)
        if not path.exists():
            statuses[trade_date] = IndexGlobalTargetFileStatus(
                layer=layer,
                trade_date=trade_date,
                path=str(path),
                status="missing",
                reason_code="file_missing",
                row_count=0,
                file_size_bytes=0,
            )
        else:
            existing_paths.append(path)

    schemas = _describe_files(connection, existing_paths, schema=schema)
    valid_paths = [path for path in existing_paths if schemas.get(path) == expected]
    for path in existing_paths:
        if path not in valid_paths:
            trade_date = path.parent.name.removeprefix("trade_date=")
            statuses[trade_date] = IndexGlobalTargetFileStatus(
                layer=layer,
                trade_date=trade_date,
                path=str(path),
                status="invalid_existing",
                reason_code="schema_mismatch",
                row_count=0,
                file_size_bytes=path.stat().st_size,
            )

    if valid_paths:
        try:
            metric_rows = connection.execute(
                _target_row_query(layer=layer, schema=schema),
                [[str(path) for path in valid_paths]],
            ).fetchall()
        except Exception as exc:
            raise IndexGlobalBootstrapPlanError(
                f"{layer} target batch scan failed: {exc}"
            ) from exc
        metrics_by_path = {
            str(Path(str(row[0])).resolve()): tuple(row[1:]) for row in metric_rows
        }
        for path in valid_paths:
            trade_date = path.parent.name.removeprefix("trade_date=")
            metrics = metrics_by_path.get(str(path.resolve()), (0, 0, 0, 0, 0))
            row_count = int(metrics[0] or 0)
            invalid = any(int(value or 0) != 0 for value in metrics[1:])
            statuses[trade_date] = IndexGlobalTargetFileStatus(
                layer=layer,
                trade_date=trade_date,
                path=str(path),
                status="invalid_existing" if invalid else "valid_existing",
                reason_code="core_contract_failed" if invalid else "ready",
                row_count=row_count,
                file_size_bytes=path.stat().st_size,
            )

    ordered = tuple(statuses[trade_date] for trade_date in dates)
    invalid_samples = tuple(
        status.to_dict() for status in ordered if status.status == "invalid_existing"
    )[:_SAMPLE_LIMIT]
    audit = IndexGlobalTargetLayerAudit(
        layer=layer,
        expected_file_count=len(dates),
        missing_count=sum(status.status == "missing" for status in ordered),
        valid_existing_count=sum(status.status == "valid_existing" for status in ordered),
        invalid_existing_count=sum(status.status == "invalid_existing" for status in ordered),
        existing_bytes=sum(status.file_size_bytes for status in ordered),
        scan_elapsed_ms=(perf_counter() - started) * 1000,
        invalid_samples=invalid_samples,
    )
    return audit, ordered


def run_dry_run(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    start_date: str | None = None,
    end_date: str | None = None,
) -> IndexGlobalBootstrapDryRunReport:
    """Build the P7 read-only report; no Tushare or Dagster API is called."""

    started = perf_counter()
    date_plan = build_date_plan(start_date=start_date, end_date=end_date)
    with duckdb_resource.connect() as connection:
        raw_audit, raw_statuses = _audit_layer(
            connection=connection,
            lake_root=lake_root,
            dates=date_plan.expected_natural_dates,
            layer="raw",
        )
        silver_audit, silver_statuses = _audit_layer(
            connection=connection,
            lake_root=lake_root,
            dates=date_plan.expected_natural_dates,
            layer="silver",
        )
    stop_reason_codes = tuple(
        reason
        for reason, count in (
            ("raw_invalid_existing_target", raw_audit.invalid_existing_count),
            ("silver_invalid_existing_target", silver_audit.invalid_existing_count),
        )
        if count
    )
    return IndexGlobalBootstrapDryRunReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        date_plan=date_plan,
        source_probe="not_requested",
        phase_count=len(INDEX_GLOBAL_NORMAL_PHASES),
        estimated_source_request_count=len(date_plan.expected_natural_dates)
        * len(INDEX_GLOBAL_NORMAL_PHASES),
        expected_raw_file_count=len(date_plan.expected_natural_dates),
        expected_silver_file_count=len(date_plan.expected_natural_dates),
        target_audits=(raw_audit, silver_audit),
        target_files=raw_statuses + silver_statuses,
        should_stop=bool(stop_reason_codes),
        stop_reason_codes=stop_reason_codes,
        elapsed_ms=(perf_counter() - started) * 1000,
    )


def write_report(report: IndexGlobalBootstrapDryRunReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "IndexGlobalBootstrapDryRunReport",
    "IndexGlobalBootstrapPlanError",
    "IndexGlobalDatePlan",
    "IndexGlobalTargetFileStatus",
    "IndexGlobalTargetLayerAudit",
    "build_date_plan",
    "run_dry_run",
    "write_report",
]
