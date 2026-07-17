"""Bounded Bootstrap planning and isolated sample loading for board technical serving.

This module deliberately does not provide a formal-table ``apply`` path.  The
source audit and sample staging path must pass before a separately approved
DDL/full-load implementation can be opened.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GoldDcDailyTechnicalAudit,
    batch_gold_dc_daily_technical_audit,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    gold_dc_daily_technical_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.dc_daily_technical import (
    DC_DAILY_TECHNICAL_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
)


BOOTSTRAP_BATCH_SIZE = 50_000
BOOTSTRAP_MAX_BATCH_SIZE = 50_000
BOOTSTRAP_DATASET = "gold_dc_daily_technical"
CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SAFE_STAGING_TABLE = re.compile(r"^(?:tmp|staging)_[A-Za-z0-9_]+$")


class DcDailyTechnicalClickHouseBootstrapError(RuntimeError):
    """Raised when the bounded Bootstrap plan cannot continue safely."""


@dataclass(frozen=True, slots=True)
class DcDailyTechnicalClickHouseBootstrapPlan:
    lake_root: Path
    expected_trade_dates: tuple[str, ...]
    audits: Mapping[str, GoldDcDailyTechnicalAudit]
    source_file_count: int
    source_row_count: int
    source_bytes: int
    batch_size: int
    estimated_batch_count: int
    plan_fingerprint: str
    elapsed_ms: int
    target_audit: Mapping[str, object] = field(default_factory=dict)
    precondition_errors: tuple[str, ...] = ()

    @property
    def failed_dates(self) -> tuple[str, ...]:
        return tuple(
            trade_date
            for trade_date in self.expected_trade_dates
            if not self.audits[trade_date].passed
        )

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors or self.failed_dates)

    def to_dict(self) -> dict[str, object]:
        failed_samples = [
            {
                "trade_date": trade_date,
                "reason_code": self.audits[trade_date].reason_code,
                "failed_rules": list(self.audits[trade_date].failed_rules),
                "checked_row_count": self.audits[trade_date].checked_row_count,
            }
            for trade_date in self.failed_dates[:20]
        ]
        return {
            "schema_version": 1,
            "dataset": BOOTSTRAP_DATASET,
            "target_table": DC_DAILY_TECHNICAL_SERVING_TABLE,
            "lake_root": str(self.lake_root),
            "expected_trade_dates": list(self.expected_trade_dates),
            "expected_date_count": len(self.expected_trade_dates),
            "expected_start_date": self.expected_trade_dates[0]
            if self.expected_trade_dates
            else None,
            "expected_end_date": self.expected_trade_dates[-1]
            if self.expected_trade_dates
            else None,
            "source_file_count": self.source_file_count,
            "source_row_count": self.source_row_count,
            "source_bytes": self.source_bytes,
            "batch_size": self.batch_size,
            "estimated_batch_count": self.estimated_batch_count,
            "plan_fingerprint": self.plan_fingerprint,
            "elapsed_ms": self.elapsed_ms,
            "target_audit": dict(self.target_audit),
            "precondition_errors": list(self.precondition_errors),
            "failed_date_count": len(self.failed_dates),
            "failed_date_samples": failed_samples,
            "should_stop": self.should_stop,
        }


def _normalize_dates(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


def _expected_dates_from_calendar(connection, lake_root: Path) -> tuple[str, ...]:
    calendar_relation = read_parquet(
        silver_trade_calendar_path(lake_root),
        hive_partitioning=False,
    )
    return tuple(
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT CAST(trade_date AS DATE)::VARCHAR
            FROM {calendar_relation}
            WHERE exchange = 'SSE' AND is_open = true
            GROUP BY CAST(trade_date AS DATE)
            ORDER BY CAST(trade_date AS DATE)
            """
        ).fetchall()
    )


def _existing_gold_trade_dates(lake_root: Path) -> tuple[str, ...]:
    sample_path = gold_dc_daily_technical_path(lake_root, "2000-01-01")
    dataset_root = sample_path.parent.parent
    dates: list[str] = []
    for path in dataset_root.glob("trade_date=*/part-000.parquet"):
        partition_name = path.parent.name
        if not partition_name.startswith("trade_date=") or not path.is_file():
            continue
        trade_date = partition_name.split("=", 1)[1]
        try:
            dates.append(date.fromisoformat(trade_date).isoformat())
        except ValueError as error:
            raise DcDailyTechnicalClickHouseBootstrapError(
                f"Invalid Gold trade-date partition: {partition_name}"
            ) from error
    normalized = _normalize_dates(dates)
    if not normalized:
        raise DcDailyTechnicalClickHouseBootstrapError(
            f"No Gold {BOOTSTRAP_DATASET} partition files found under {dataset_root}"
        )
    return normalized


def _select_dates(
    expected_dates: Sequence[str],
    *,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    selected = tuple(
        trade_date
        for trade_date in _normalize_dates(expected_dates)
        if (start_date is None or trade_date >= start_date)
        and (end_date is None or trade_date <= end_date)
    )
    if not selected:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "Bootstrap date selection is empty."
        )
    return selected


def _plan_fingerprint(
    *,
    trade_dates: Sequence[str],
    row_counts: Mapping[str, int],
    batch_size: int,
) -> str:
    payload = {
        "dataset": BOOTSTRAP_DATASET,
        "table": DC_DAILY_TECHNICAL_SERVING_TABLE,
        "columns": list(DC_DAILY_TECHNICAL_SERVING_COLUMNS),
        "trade_dates": list(trade_dates),
        "row_counts": {key: row_counts[key] for key in trade_dates},
        "batch_size": batch_size,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0 or batch_size > BOOTSTRAP_MAX_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be between 1 and {BOOTSTRAP_MAX_BATCH_SIZE}"
        )


def build_gold_dc_daily_technical_bootstrap_plan(
    *,
    connection,
    lake_root: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int = BOOTSTRAP_BATCH_SIZE,
    target_audit: Mapping[str, object] | None = None,
) -> DcDailyTechnicalClickHouseBootstrapPlan:
    """Build a source-only plan using one bounded DuckDB audit."""

    _validate_batch_size(batch_size)
    existing_gold_dates = _existing_gold_trade_dates(lake_root)
    effective_start_date = start_date or DC_DAILY_TECHNICAL_HISTORY_START_DATE
    effective_end_date = end_date or existing_gold_dates[-1]
    if effective_start_date < DC_DAILY_TECHNICAL_HISTORY_START_DATE:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "Bootstrap start date is earlier than the Gold dataset history start: "
            f"{DC_DAILY_TECHNICAL_HISTORY_START_DATE}"
        )
    expected_dates = _select_dates(
        _expected_dates_from_calendar(connection, lake_root),
        start_date=effective_start_date,
        end_date=effective_end_date,
    )
    started = perf_counter()
    audits = batch_gold_dc_daily_technical_audit(
        connection=connection,
        lake_root=lake_root,
        trade_dates=expected_dates,
    )
    row_counts = {
        trade_date: int(audits[trade_date].checked_row_count)
        for trade_date in expected_dates
    }
    source_paths = {
        trade_date: gold_dc_daily_technical_path(lake_root, trade_date)
        for trade_date in expected_dates
    }
    source_file_count = sum(path.is_file() for path in source_paths.values())
    source_bytes = sum(
        path.stat().st_size for path in source_paths.values() if path.is_file()
    )
    source_row_count = sum(row_counts.values())
    fingerprint = _plan_fingerprint(
        trade_dates=expected_dates,
        row_counts=row_counts,
        batch_size=batch_size,
    )
    precondition_errors: list[str] = []
    if len(audits) != len(expected_dates):
        precondition_errors.append("audit_date_coverage_mismatch")
    if source_file_count != len(expected_dates):
        precondition_errors.append("gold_file_count_mismatch")
    return DcDailyTechnicalClickHouseBootstrapPlan(
        lake_root=lake_root,
        expected_trade_dates=expected_dates,
        audits=audits,
        source_file_count=source_file_count,
        source_row_count=source_row_count,
        source_bytes=source_bytes,
        batch_size=batch_size,
        estimated_batch_count=(
            (source_row_count + batch_size - 1) // batch_size
            if source_row_count
            else 0
        ),
        plan_fingerprint=fingerprint,
        elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
        target_audit=target_audit or {},
        precondition_errors=tuple(precondition_errors),
    )


def _gold_union_sql(lake_root: Path, trade_dates: Sequence[str]) -> str:
    projection = ", ".join(DC_DAILY_TECHNICAL_SERVING_COLUMNS)
    selects = []
    for trade_date in trade_dates:
        path = gold_dc_daily_technical_path(lake_root, trade_date)
        selects.append(
            f"SELECT {projection} FROM {read_parquet(path, hive_partitioning=False)}"
        )
    if not selects:
        raise ValueError("trade_dates must not be empty")
    return " UNION ALL ".join(selects)


def iter_gold_clickhouse_rows(
    *,
    connection,
    lake_root: Path,
    trade_dates: Sequence[str],
    batch_size: int = BOOTSTRAP_BATCH_SIZE,
    updated_at: datetime | None = None,
) -> Iterator[list[tuple[Any, ...]]]:
    """Yield explicit ClickHouse rows without loading the full history."""

    _validate_batch_size(batch_size)
    timestamp = updated_at or datetime.now(CN_A_TIMEZONE).replace(tzinfo=None)
    relation = _gold_union_sql(lake_root, _normalize_dates(trade_dates))
    cursor = connection.execute(
        f"SELECT {', '.join(DC_DAILY_TECHNICAL_SERVING_COLUMNS)} FROM ({relation}) "
        "ORDER BY trade_date, category, ts_code"
    )
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        yield [(*tuple(row), timestamp) for row in rows]


def _safe_staging_table(table_name: str) -> str:
    if table_name == DC_DAILY_TECHNICAL_SERVING_TABLE:
        raise ValueError("sample staging cannot be the formal serving table")
    if not _SAFE_STAGING_TABLE.fullmatch(table_name):
        raise ValueError(
            "sample staging table must start with tmp_ or staging_ and contain "
            "only ASCII letters, digits and underscores"
        )
    return table_name


def _validate_sample_staging_schema(client, table: str) -> None:
    schema_rows = client.execute(f"DESCRIBE TABLE {table}")
    actual_columns = tuple(str(row[0]) for row in schema_rows)
    expected_columns = tuple(
        (*DC_DAILY_TECHNICAL_SERVING_COLUMNS, "updated_at")
    )
    if actual_columns != expected_columns:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "sample staging schema mismatch: "
            f"expected={expected_columns}, actual={actual_columns}"
        )


def insert_sample_rows(
    *,
    client,
    staging_table: str,
    row_batches: Iterator[list[tuple[Any, ...]]],
) -> dict[str, int | str]:
    """Insert into an explicitly isolated, pre-created sample table only."""

    table = _safe_staging_table(staging_table)
    _validate_sample_staging_schema(client, table)
    inserted_rows = 0
    batch_count = 0
    started = perf_counter()
    columns = ", ".join((*DC_DAILY_TECHNICAL_SERVING_COLUMNS, "updated_at"))
    for batch in row_batches:
        if not batch:
            continue
        client.execute(f"INSERT INTO {table} ({columns}) VALUES", batch)
        inserted_rows += len(batch)
        batch_count += 1
    count_rows = client.execute(f"SELECT count() FROM {table}")
    if not count_rows or int(count_rows[0][0]) != inserted_rows:
        actual_rows = int(count_rows[0][0]) if count_rows else -1
        raise DcDailyTechnicalClickHouseBootstrapError(
            "sample staging row count mismatch: "
            f"inserted={inserted_rows}, staging={actual_rows}"
        )
    return {
        "staging_table": table,
        "inserted_row_count": inserted_rows,
        "staging_row_count": int(count_rows[0][0]),
        "batch_count": batch_count,
        "elapsed_ms": int((perf_counter() - started) * 1000),
    }


def audit_sample_staging(
    *,
    client,
    staging_table: str,
    expected_rows_by_date: Mapping[str, int],
) -> dict[str, object]:
    """Validate sample staging by date, row count and business-key uniqueness."""

    table = _safe_staging_table(staging_table)
    _validate_sample_staging_schema(client, table)
    rows = client.execute(
        f"""
        SELECT trade_date, count(),
               uniqExact(tuple(ts_code, trade_date, category))
        FROM {table}
        GROUP BY trade_date
        ORDER BY trade_date
        """
    )
    actual_rows_by_date = {str(row[0]): int(row[1]) for row in rows}
    actual_unique_by_date = {str(row[0]): int(row[2]) for row in rows}
    expected = {str(key): int(value) for key, value in expected_rows_by_date.items()}
    if actual_rows_by_date != expected:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "sample staging date row count mismatch: "
            f"expected={expected}, actual={actual_rows_by_date}"
        )
    duplicate_dates = [
        trade_date
        for trade_date, row_count in actual_rows_by_date.items()
        if actual_unique_by_date[trade_date] != row_count
    ]
    if duplicate_dates:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "sample staging duplicate business keys: " + ",".join(duplicate_dates)
        )
    return {
        "staging_table": table,
        "trade_date_count": len(actual_rows_by_date),
        "row_count": sum(actual_rows_by_date.values()),
        "unique_key_count": sum(actual_unique_by_date.values()),
        "duplicate_trade_dates": duplicate_dates,
    }


def write_bootstrap_report(
    plan: DcDailyTechnicalClickHouseBootstrapPlan,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def clickhouse_resource_from_env(prefix: str = "CLICKHOUSE") -> ClickhouseResource:
    """Build a ClickHouse resource from an explicit environment prefix."""

    import os

    required = {
        "host": os.environ.get(f"{prefix}_HOST"),
        "port": os.environ.get(f"{prefix}_PORT"),
        "user": os.environ.get(f"{prefix}_USER"),
        "password": os.environ.get(f"{prefix}_PASSWORD", ""),
        "database": os.environ.get(f"{prefix}_DATABASE"),
    }
    missing = [name for name in ("host", "port", "user", "database") if not required[name]]
    if missing:
        raise ValueError(f"missing ClickHouse environment values: {', '.join(missing)}")
    return ClickhouseResource(
        host=required["host"],
        port=int(required["port"]),
        user=required["user"],
        password=required["password"],
        database=required["database"],
    )


__all__ = [
    "BOOTSTRAP_BATCH_SIZE",
    "DcDailyTechnicalClickHouseBootstrapError",
    "DcDailyTechnicalClickHouseBootstrapPlan",
    "audit_sample_staging",
    "build_gold_dc_daily_technical_bootstrap_plan",
    "clickhouse_resource_from_env",
    "insert_sample_rows",
    "iter_gold_clickhouse_rows",
    "write_bootstrap_report",
]
