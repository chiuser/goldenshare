"""Read-only planning and source audit for the dc board Bootstrap.

This module intentionally has no promotion path.  It may read the standard
trade calendar, Tushare, the read-only Prod member source, and existing lake
files, but it never writes a lake file or a Dagster event.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any

from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
    batch_raw_dc_index_lake_readiness,
    batch_raw_dc_member_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_silver_lake_readiness import (
    batch_silver_dc_daily_lake_readiness,
    batch_silver_dc_index_lake_readiness,
    batch_silver_dc_member_lake_readiness,
)
from orchestrator.defs.assets.dc_board import _RAW_TYPES, DC_REQUEST_POLICY
from orchestrator.defs.bootstrap.dc_board_bootstrap import (
    DC_MEMBER_BOOTSTRAP_AUDIT_SQL,
    DC_MEMBER_BOOTSTRAP_SELECT_SQL,
    _row_mapping,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_FIELDS,
    DC_DAILY_HISTORY_START_DATE,
    DC_DAILY_PAGE_LIMIT,
    DC_DAILY_CATEGORIES,
    DC_INDEX_FIELDS,
    DC_INDEX_HISTORY_START_DATE,
    DC_INDEX_TYPES,
    DC_INDEX_PAGE_LIMIT,
    DC_MEMBER_FIELDS,
    DC_MEMBER_HISTORY_START_DATE,
    DC_MEMBER_PAGE_LIMIT,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedCodeRequestResult,
    BoundedPageRequestResult,
    TushareRequestPolicy,
    execute_bounded_code_pages,
    execute_bounded_pages,
)


_BOARD_CODE_RE = r"^BK[0-9]{4}\.DC$"
_STOCK_CODE_RE = r"^[0-9]{6}\.(SZ|SH|BJ)$"
_DATE_RE = re.compile(r"^\d{8}$")
_SAMPLE_LIMIT = 20


class DcBoardBootstrapPlanError(ValueError):
    """Raised when the read-only Bootstrap plan cannot be trusted."""


@dataclass(frozen=True, slots=True)
class DcBoardDatePlan:
    dataset: str
    start_date: str
    end_date: str
    expected_trade_dates: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"expected_trade_dates": list(self.expected_trade_dates)}


@dataclass(frozen=True, slots=True)
class DcBoardSourceAudit:
    dataset: str
    trade_date: str
    source_method: str
    source_row_count: int
    request_count: int
    page_count: int
    retry_count: int
    chunk_count: int
    elapsed_ms: float
    duplicate_key_count: int
    invalid_code_count: int
    out_of_partition_count: int
    identity_failure_count: int
    blank_name_count: int
    empty_result: bool
    failed: bool
    failure_reason: str | None = None
    failure_samples: tuple[str, ...] = ()
    batch_elapsed_ms: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"failure_samples": list(self.failure_samples)}


@dataclass(frozen=True, slots=True)
class DcBoardTargetAudit:
    layer: str
    dataset: str
    expected_count: int
    missing_count: int
    valid_existing_count: int
    invalid_existing_count: int
    scanned_file_count: int
    existing_bytes: int
    invalid_trade_dates: tuple[str, ...] = ()
    invalid_reasons: tuple[str, ...] = ()
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "invalid_trade_dates": list(self.invalid_trade_dates),
            "invalid_reasons": list(self.invalid_reasons),
        }


@dataclass(frozen=True, slots=True)
class DcBoardBootstrapDryRunReport:
    generated_at: str
    lake_root: str
    requested_start_date: str | None
    requested_end_date: str | None
    effective_end_date: str
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    date_plans: tuple[DcBoardDatePlan, ...]
    source_audits: tuple[DcBoardSourceAudit, ...]
    target_audits: tuple[DcBoardTargetAudit, ...]
    expected_file_count: int
    expected_raw_file_count: int
    expected_silver_file_count: int
    source_row_count_by_dataset: Mapping[str, int]
    request_count: int
    page_count: int
    retry_count: int
    source_elapsed_ms_by_dataset: Mapping[str, float]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "requested_start_date": self.requested_start_date,
            "requested_end_date": self.requested_end_date,
            "effective_end_date": self.effective_end_date,
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "date_plans": [plan.to_dict() for plan in self.date_plans],
            "source_audits": [audit.to_dict() for audit in self.source_audits],
            "target_audits": [audit.to_dict() for audit in self.target_audits],
            "expected_file_count": self.expected_file_count,
            "expected_raw_file_count": self.expected_raw_file_count,
            "expected_silver_file_count": self.expected_silver_file_count,
            "source_row_count_by_dataset": dict(self.source_row_count_by_dataset),
            "request_count": self.request_count,
            "page_count": self.page_count,
            "retry_count": self.retry_count,
            "source_elapsed_ms_by_dataset": dict(self.source_elapsed_ms_by_dataset),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class _DatasetSpec:
    dataset: str
    start_date: str
    source_method: str
    raw_path_builder: Any
    silver_path_builder: Any
    raw_schema: Sequence[Any]
    key_columns: tuple[str, ...]


_DATASET_SPECS = {
    "dc_index": _DatasetSpec(
        dataset="dc_index",
        start_date=DC_INDEX_HISTORY_START_DATE,
        source_method="tushare_api",
        raw_path_builder=raw_dc_index_path,
        silver_path_builder=silver_dc_index_path,
        raw_schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
    ),
    "dc_member": _DatasetSpec(
        dataset="dc_member",
        start_date=DC_MEMBER_HISTORY_START_DATE,
        source_method="prod_db_readonly_export",
        raw_path_builder=raw_dc_member_path,
        silver_path_builder=silver_dc_member_path,
        raw_schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        key_columns=("trade_date", "ts_code", "con_code"),
    ),
    "dc_daily": _DatasetSpec(
        dataset="dc_daily",
        start_date=DC_DAILY_HISTORY_START_DATE,
        source_method="tushare_api",
        raw_path_builder=raw_dc_daily_path,
        silver_path_builder=silver_dc_daily_path,
        raw_schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        key_columns=("ts_code", "trade_date", "category"),
    ),
}

_RAW_READINESS = {
    "dc_index": batch_raw_dc_index_lake_readiness,
    "dc_member": batch_raw_dc_member_lake_readiness,
    "dc_daily": batch_raw_dc_daily_lake_readiness,
}
_SILVER_READINESS = {
    "dc_index": batch_silver_dc_index_lake_readiness,
    "dc_member": batch_silver_dc_member_lake_readiness,
    "dc_daily": batch_silver_dc_daily_lake_readiness,
}


def _normalize_iso_date(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise DcBoardBootstrapPlanError(
            f"{field_name} must be YYYY-MM-DD: {value!r}"
        ) from exc


def _fingerprint(dataset: str, dates: Sequence[str]) -> str:
    payload = "\n".join((dataset, *dates)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_date_plans(
    *,
    connection,
    calendar_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    datasets: Sequence[str] = tuple(_DATASET_SPECS),
) -> tuple[DcBoardDatePlan, ...]:
    """Build deterministic date plans from the standardized calendar only."""

    if not calendar_path.exists():
        raise DcBoardBootstrapPlanError(f"silver trade calendar is missing: {calendar_path}")
    selected_datasets = tuple(dict.fromkeys(datasets))
    unknown = tuple(dataset for dataset in selected_datasets if dataset not in _DATASET_SPECS)
    if unknown:
        raise DcBoardBootstrapPlanError(f"unknown dc board dataset(s): {unknown}")
    normalized_start = _normalize_iso_date(start_date, field_name="start_date")
    normalized_end = _normalize_iso_date(end_date, field_name="end_date")
    today = date.today().isoformat()
    if normalized_start is not None and normalized_start > today:
        raise DcBoardBootstrapPlanError(
            f"start_date {normalized_start} is in the future relative to today {today}"
        )
    if normalized_end is not None and normalized_end > today:
        raise DcBoardBootstrapPlanError(
            f"end_date {normalized_end} is in the future relative to today {today}"
        )
    effective_end = normalized_end or today

    invalid_date_count = int(
        connection.execute(
            """
            SELECT count(*)
            FROM read_parquet(?)
            WHERE exchange = 'SSE' AND is_open = true AND trade_date IS NULL
            """,
            [str(calendar_path)],
        ).fetchone()[0]
    )
    if invalid_date_count:
        raise DcBoardBootstrapPlanError(
            f"calendar has {invalid_date_count} SSE open rows with null trade_date"
        )
    duplicate_rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE), count(*)
        FROM read_parquet(?)
        WHERE exchange = 'SSE' AND is_open = true
        GROUP BY CAST(trade_date AS DATE)
        HAVING count(*) <> 1
        ORDER BY CAST(trade_date AS DATE)
        """,
        [str(calendar_path)],
    ).fetchall()
    if duplicate_rows:
        raise DcBoardBootstrapPlanError(
            "calendar has duplicate SSE open dates: "
            f"{tuple((str(row[0]), int(row[1])) for row in duplicate_rows[:_SAMPLE_LIMIT])}"
        )
    calendar_dates = tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT CAST(trade_date AS DATE)
            FROM read_parquet(?)
            WHERE exchange = 'SSE' AND is_open = true
            ORDER BY CAST(trade_date AS DATE)
            """,
            [str(calendar_path)],
        ).fetchall()
    )
    if not calendar_dates:
        raise DcBoardBootstrapPlanError("calendar has no SSE open dates")
    if effective_end < calendar_dates[0]:
        raise DcBoardBootstrapPlanError(
            f"end_date {effective_end} is before the first SSE open date {calendar_dates[0]}"
        )

    plans: list[DcBoardDatePlan] = []
    for dataset in selected_datasets:
        spec = _DATASET_SPECS[dataset]
        selected = tuple(
            trade_date
            for trade_date in calendar_dates
            if trade_date >= max(spec.start_date, normalized_start or spec.start_date)
            and trade_date <= effective_end
        )
        if not selected:
            raise DcBoardBootstrapPlanError(
                f"no SSE open dates for {dataset} after {spec.start_date}"
            )
        plans.append(
            DcBoardDatePlan(
                dataset=dataset,
                start_date=selected[0],
                end_date=selected[-1],
                expected_trade_dates=selected,
                fingerprint=_fingerprint(dataset, selected),
            )
        )
    return tuple(plans)


def _normalize_trade_date_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if _DATE_RE.fullmatch(text) else None


def _extract_rows(result, fields: Sequence[str]) -> list[dict[str, object]]:
    if tuple(result.columns) != tuple(fields):
        raise DcBoardBootstrapPlanError(
            f"Tushare response columns drifted: expected {tuple(fields)}, got {result.columns}"
        )
    rows: list[dict[str, object]] = []
    for source_row in result.rows:
        row = {field: source_row.get(field) for field in fields}
        if "trade_date" in row:
            row["trade_date"] = _normalize_trade_date_value(row["trade_date"])
        rows.append(row)
    return rows


def _create_audit_table(connection, dataset: str) -> None:
    fields = tuple(_RAW_TYPES[dataset])
    definitions = ", ".join(
        f'"{field}" {_RAW_TYPES[dataset][field]}' for field in fields
    )
    connection.execute("DROP TABLE IF EXISTS dc_board_bootstrap_audit_rows")
    connection.execute(f"CREATE TEMP TABLE dc_board_bootstrap_audit_rows ({definitions})")


def _append_audit_rows(
    *,
    connection,
    dataset: str,
    rows: Sequence[Mapping[str, object]],
) -> None:
    if not rows:
        return
    fields = tuple(_RAW_TYPES[dataset])
    try:
        import pandas as pd
    except ModuleNotFoundError:
        placeholders = ", ".join("?" for _ in fields)
        quoted_columns = ", ".join(f'"{field}"' for field in fields)
        connection.executemany(
            f"INSERT INTO dc_board_bootstrap_audit_rows ({quoted_columns}) VALUES ({placeholders})",
            [[row.get(field) for field in fields] for row in rows],
        )
        return
    frame = pd.DataFrame.from_records(
        [[row.get(field) for field in fields] for row in rows],
        columns=fields,
    )
    connection.append("dc_board_bootstrap_audit_rows", frame, by_name=True)


def _audit_rows(
    *,
    connection,
    dataset: str,
    rows: Sequence[Mapping[str, object]],
    trade_date: str,
) -> tuple[int, int, int, int, int, tuple[str, ...]]:
    _create_audit_table(connection, dataset)
    _append_audit_rows(connection=connection, dataset=dataset, rows=rows)
    return _audit_table(connection=connection, dataset=dataset, trade_date=trade_date)


def _audit_table(
    *,
    connection,
    dataset: str,
    trade_date: str,
) -> tuple[int, int, int, int, int, tuple[str, ...]]:
    key_expr = ", ".join(f'"{field}"' for field in _DATASET_SPECS[dataset].key_columns)
    if dataset == "dc_index":
        identity_expr = (
            f"ts_code IS NULL OR NOT regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '{_BOARD_CODE_RE}') "
            "OR idx_type IS NULL OR idx_type NOT IN ('行业板块', '概念板块', '地域板块')"
        )
    elif dataset == "dc_member":
        identity_expr = (
            f"ts_code IS NULL OR NOT regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '{_BOARD_CODE_RE}') "
            f"OR con_code IS NULL OR NOT regexp_full_match(trim(CAST(con_code AS VARCHAR)), '{_STOCK_CODE_RE}')"
        )
    else:
        identity_expr = (
            f"ts_code IS NULL OR NOT regexp_full_match(trim(CAST(ts_code AS VARCHAR)), '{_BOARD_CODE_RE}') "
            "OR category IS NULL OR category NOT IN ('行业板块', '概念板块', '地域板块')"
        )
    blank_name_expr = (
        "sum(CASE WHEN name IS NULL OR trim(CAST(name AS VARCHAR)) = '' THEN 1 ELSE 0 END)"
        if dataset in {"dc_index", "dc_member"}
        else "0"
    )
    row_count, duplicate_count, invalid_code_count, out_of_partition_count, blank_name_count = connection.execute(
        f"""
        SELECT
            count(*),
            (SELECT count(*) FROM (
                SELECT {key_expr}
                FROM dc_board_bootstrap_audit_rows
                GROUP BY {key_expr}
                HAVING count(*) > 1
            )),
            sum(CASE WHEN {identity_expr} THEN 1 ELSE 0 END),
            sum(CASE WHEN trade_date IS NULL OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> ? THEN 1 ELSE 0 END),
            {blank_name_expr}
        FROM dc_board_bootstrap_audit_rows
        """,
        [_normalize_trade_date_value(trade_date)],
    ).fetchone()
    samples = tuple(
        str(row[0])
        for row in connection.execute(
            f"SELECT DISTINCT CAST(trade_date AS VARCHAR) FROM dc_board_bootstrap_audit_rows "
            "WHERE trade_date IS NULL OR replace(trim(CAST(trade_date AS VARCHAR)), '-', '') <> ? "
            "LIMIT ?",
            [_normalize_trade_date_value(trade_date), _SAMPLE_LIMIT],
        ).fetchall()
    )
    return (
        int(row_count or 0),
        int(duplicate_count or 0),
        int(invalid_code_count or 0),
        int(out_of_partition_count or 0),
        int(blank_name_count or 0),
        samples,
    )


def _source_audit_from_result(
    *,
    connection,
    dataset: str,
    trade_date: str,
    source_method: str,
    result: BoundedCodeRequestResult | BoundedPageRequestResult,
    rows: Sequence[Mapping[str, object]],
    chunk_count: int = 0,
    extra_failure: str | None = None,
) -> DcBoardSourceAudit:
    source_row_count, duplicate_count, invalid_code_count, out_of_partition_count, blank_name_count, samples = _audit_rows(
        connection=connection,
        dataset=dataset,
        rows=rows,
        trade_date=trade_date,
    )
    failed = (
        not result.ready
        or not rows
        or duplicate_count
        or invalid_code_count
        or out_of_partition_count
        or blank_name_count
        or extra_failure is not None
    )
    reasons: list[str] = []
    if not result.ready:
        reasons.append(result.blocked_reason or "bounded_request_failed")
    if not rows:
        reasons.append("empty_result")
    if duplicate_count:
        reasons.append("duplicate_business_key")
    if invalid_code_count:
        reasons.append("invalid_identity_fields")
    if out_of_partition_count:
        reasons.append("trade_date_out_of_partition")
    if blank_name_count:
        reasons.append("blank_name")
    if extra_failure:
        reasons.append(extra_failure)
    if isinstance(result, BoundedCodeRequestResult):
        result_failures = tuple(
            f"{failure.code}:{failure.category}:{failure.message[:240]}"
            for failure in result.failed_codes[:_SAMPLE_LIMIT]
        )
    else:
        result_failures = tuple(
            f"{failure.code}:{failure.category}:{failure.message[:240]}"
            for failure in result.failed_pages[:_SAMPLE_LIMIT]
        )
    failure_samples = tuple(
        dict.fromkeys((*samples, *result_failures, *(reasons[:_SAMPLE_LIMIT])))
    )
    return DcBoardSourceAudit(
        dataset=dataset,
        trade_date=trade_date,
        source_method=source_method,
        source_row_count=source_row_count,
        request_count=result.request_count,
        page_count=(
            sum(result.page_counts.values())
            if isinstance(result, BoundedCodeRequestResult)
            else result.page_count
        ),
        retry_count=result.retry_count,
        chunk_count=chunk_count,
        elapsed_ms=round(result.elapsed_ms, 3),
        duplicate_key_count=duplicate_count,
        invalid_code_count=invalid_code_count,
        out_of_partition_count=out_of_partition_count,
        identity_failure_count=invalid_code_count,
        blank_name_count=blank_name_count,
        empty_result=not rows,
        failed=bool(failed),
        failure_reason=";".join(reasons) if reasons else None,
        failure_samples=failure_samples,
    )


def audit_tushare_partition(
    *,
    connection,
    tushare: TushareResource,
    dataset: str,
    trade_date: str,
    policy: TushareRequestPolicy = DC_REQUEST_POLICY,
) -> DcBoardSourceAudit:
    """Read and validate one Tushare date without creating a lake file."""

    started = perf_counter()
    if dataset not in {"dc_index", "dc_daily"}:
        raise ValueError(f"Tushare source audit does not support dataset: {dataset}")
    if dataset == "dc_index":
        result = execute_bounded_code_pages(
            codes=DC_INDEX_TYPES,
            request_page=lambda idx_type, offset: tushare.call(
                "dc_index",
                {"trade_date": trade_date.replace("-", ""), "idx_type": idx_type, "limit": DC_INDEX_PAGE_LIMIT, "offset": offset},
                DC_INDEX_FIELDS,
            ),
            extract_rows=lambda response: _extract_rows(response, DC_INDEX_FIELDS),
            page_size=DC_INDEX_PAGE_LIMIT,
            policy=policy,
            row_key=lambda row: (row.get("ts_code"), row.get("trade_date")),
        )
        rows = [row for code in DC_INDEX_TYPES for row in result.rows_by_code.get(code, [])]
        mismatched = any(row.get("idx_type") not in DC_INDEX_TYPES for row in rows)
        audit = _source_audit_from_result(
            connection=connection,
            dataset=dataset,
            trade_date=trade_date,
            source_method="tushare_api",
            result=result,
            rows=rows,
            extra_failure="idx_type_mismatch" if mismatched else None,
        )
    else:
        page_result = execute_bounded_pages(
            request_page=lambda offset: tushare.call(
                "dc_daily",
                {"trade_date": trade_date.replace("-", ""), "limit": DC_DAILY_PAGE_LIMIT, "offset": offset},
                DC_DAILY_FIELDS,
            ),
            extract_rows=lambda response: _extract_rows(response, DC_DAILY_FIELDS),
            page_size=DC_DAILY_PAGE_LIMIT,
            policy=policy,
            scope=f"dc_daily:{trade_date}",
            row_key=lambda row: (row.get("ts_code"), row.get("trade_date"), row.get("category")),
        )
        audit = _source_audit_from_result(
            connection=connection,
            dataset=dataset,
            trade_date=trade_date,
            source_method="tushare_api",
            result=page_result,
            rows=page_result.rows,
            extra_failure=None,
        )
    return DcBoardSourceAudit(
        **{
            **audit.to_dict(),
            "failure_samples": tuple(audit.failure_samples),
            "elapsed_ms": round(max(audit.elapsed_ms, (perf_counter() - started) * 1000), 3),
        }
    )


def audit_prod_member_partition(
    *,
    connection,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    chunk_size: int = 5_000,
    cursor_itersize: int = 5_000,
) -> DcBoardSourceAudit:
    """Read one Prod member date with a named cursor and bounded chunks."""

    if chunk_size <= 0 or cursor_itersize <= 0:
        raise ValueError("chunk_size and cursor_itersize must be positive")
    started = perf_counter()
    chunk_count = 0
    with prod_postgres.connect_readonly_transaction() as prod_connection:
        cursor = prod_connection.cursor(name=f"dc_member_audit_{hashlib.sha1(trade_date.encode()).hexdigest()[:12]}")
        cursor.itersize = cursor_itersize
        try:
            cursor.execute(DC_MEMBER_BOOTSTRAP_SELECT_SQL, (date.fromisoformat(trade_date),))
            while True:
                raw_rows = cursor.fetchmany(chunk_size)
                if not raw_rows:
                    break
                chunk_count += 1
                chunk = tuple(_row_mapping(row) for row in raw_rows)
                if chunk_count == 1:
                    _create_audit_table(connection, "dc_member")
                _append_audit_rows(
                    connection=connection,
                    dataset="dc_member",
                    rows=chunk,
                )
        finally:
            cursor.close()
    # Only one date is retained in memory; the report never contains source rows.
    if chunk_count == 0:
        _create_audit_table(connection, "dc_member")
    _audit_rows_result = _audit_table(
        connection=connection,
        dataset="dc_member",
        trade_date=trade_date,
    )
    row_count, duplicate_count, invalid_count, out_of_partition_count, blank_name_count, samples = _audit_rows_result
    reasons = []
    if not row_count:
        reasons.append("empty_result")
    if duplicate_count:
        reasons.append("duplicate_business_key")
    if invalid_count:
        reasons.append("invalid_identity_fields")
    if out_of_partition_count:
        reasons.append("trade_date_out_of_partition")
    if blank_name_count:
        reasons.append("blank_name")
    return DcBoardSourceAudit(
        dataset="dc_member",
        trade_date=trade_date,
        source_method="prod_db_readonly_export",
        source_row_count=row_count,
        request_count=0,
        page_count=chunk_count,
        retry_count=0,
        chunk_count=chunk_count,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
        duplicate_key_count=duplicate_count,
        invalid_code_count=invalid_count,
        out_of_partition_count=out_of_partition_count,
        identity_failure_count=invalid_count,
        blank_name_count=blank_name_count,
        empty_result=not row_count,
        failed=bool(reasons),
        failure_reason=";".join(reasons) if reasons else None,
        failure_samples=samples + tuple(reasons[:_SAMPLE_LIMIT]),
    )


def audit_prod_member_partitions(
    *,
    connection,
    prod_postgres: ProdPostgresResource,
    expected_trade_dates: Sequence[str],
    chunk_size: int = 5_000,
    cursor_itersize: int = 5_000,
) -> tuple[DcBoardSourceAudit, ...]:
    """Audit a date range with one read-only, aggregate named cursor.

    The source database performs the set-based row/key/domain aggregation. The
    named cursor still uses bounded ``fetchmany`` reads, so the planner receives
    one summary row per source date instead of transferring every member row a
    second time before the formal streaming writer.
    """

    if chunk_size <= 0 or cursor_itersize <= 0:
        raise ValueError("chunk_size and cursor_itersize must be positive")
    dates = tuple(dict.fromkeys(str(value) for value in expected_trade_dates))
    if not dates:
        return ()
    expected_set = set(dates)
    audits: dict[str, DcBoardSourceAudit] = {}
    started = perf_counter()
    cursor_fetch_count = 0
    _ = connection  # Target lake is audited separately; the source audit is DB-side.

    def aggregate_audit(row: object) -> DcBoardSourceAudit:
        if isinstance(row, Mapping):
            values = (
                row.get("trade_date"),
                row.get("source_row_count"),
                row.get("duplicate_key_count"),
                row.get("invalid_code_count"),
                row.get("out_of_partition_count"),
                row.get("blank_name_count"),
            )
        else:
            if len(row) != 6:
                raise ValueError(f"dc_member audit row must have six columns, got {len(row)}")
            values = tuple(row)
        raw_date, source_rows, duplicate, invalid, out_of_partition, blank_name = values
        trade_date = (
            raw_date.isoformat()
            if hasattr(raw_date, "isoformat")
            else str(raw_date)[:10]
        )
        reasons = []
        if not int(source_rows or 0):
            reasons.append("empty_result")
        if int(duplicate or 0):
            reasons.append("duplicate_business_key")
        if int(invalid or 0):
            reasons.append("invalid_identity_fields")
        if int(out_of_partition or 0):
            reasons.append("trade_date_out_of_partition")
        if int(blank_name or 0):
            reasons.append("blank_name")
        if trade_date not in expected_set:
            reasons.append("unexpected_source_date")
        return DcBoardSourceAudit(
            dataset="dc_member",
            trade_date=trade_date,
            source_method="prod_db_readonly_aggregate_audit",
            source_row_count=int(source_rows or 0),
            request_count=0,
            page_count=cursor_fetch_count,
            retry_count=0,
            chunk_count=cursor_fetch_count,
            elapsed_ms=0.0,
            duplicate_key_count=int(duplicate or 0),
            invalid_code_count=int(invalid or 0),
            out_of_partition_count=int(out_of_partition or 0),
            identity_failure_count=int(invalid or 0),
            blank_name_count=int(blank_name or 0),
            empty_result=not int(source_rows or 0),
            failed=bool(reasons),
            failure_reason=";".join(reasons) if reasons else None,
            failure_samples=tuple(reasons[:_SAMPLE_LIMIT]),
        )

    try:
        with prod_postgres.connect_readonly_transaction() as prod_connection:
            cursor = prod_connection.cursor(
                name=f"dc_member_audit_range_{hashlib.sha1(dates[0].encode()).hexdigest()[:12]}"
            )
            cursor.itersize = cursor_itersize
            try:
                cursor.execute(
                    DC_MEMBER_BOOTSTRAP_AUDIT_SQL,
                    (date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])),
                )
                while True:
                    rows = cursor.fetchmany(chunk_size)
                    if not rows:
                        break
                    cursor_fetch_count += 1
                    for row in rows:
                        audit = aggregate_audit(row)
                        audits[audit.trade_date] = audit
            finally:
                cursor.close()
    except Exception as exc:  # noqa: BLE001 - return a fail-closed audit.
        for trade_date in dates:
            if trade_date not in audits:
                audits[trade_date] = _source_access_failure(
                    dataset="dc_member",
                    trade_date=trade_date,
                    source_method="prod_db_readonly_aggregate_audit",
                    error=exc,
                )

    member_batch_elapsed_ms = round((perf_counter() - started) * 1000, 3)
    if any(
        audit.source_method == "prod_db_readonly_aggregate_audit"
        for audit in audits.values()
    ):
        audits = {
            trade_date: replace(audit, batch_elapsed_ms=member_batch_elapsed_ms)
            if audit.source_method == "prod_db_readonly_aggregate_audit"
            else audit
            for trade_date, audit in audits.items()
        }

    empty_started = perf_counter()
    for trade_date in dates:
        if trade_date not in audits:
            audits[trade_date] = DcBoardSourceAudit(
                dataset="dc_member",
                trade_date=trade_date,
                source_method="prod_db_readonly_aggregate_audit",
                source_row_count=0,
                request_count=0,
                page_count=cursor_fetch_count,
                retry_count=0,
                chunk_count=cursor_fetch_count,
                elapsed_ms=round((perf_counter() - empty_started) * 1000, 3),
                duplicate_key_count=0,
                invalid_code_count=0,
                out_of_partition_count=0,
                identity_failure_count=0,
                blank_name_count=0,
                empty_result=True,
                failed=True,
                failure_reason="empty_result",
                failure_samples=("empty_result",),
                batch_elapsed_ms=member_batch_elapsed_ms,
            )
    unexpected = tuple(
        audit for trade_date, audit in audits.items() if trade_date not in expected_set
    )
    return tuple(audits[trade_date] for trade_date in dates) + unexpected


def _source_access_failure(
    *,
    dataset: str,
    trade_date: str,
    source_method: str,
    error: BaseException,
) -> DcBoardSourceAudit:
    message = f"{type(error).__name__}: {error}"[:500]
    return DcBoardSourceAudit(
        dataset=dataset,
        trade_date=trade_date,
        source_method=source_method,
        source_row_count=0,
        request_count=0,
        page_count=0,
        retry_count=0,
        chunk_count=0,
        elapsed_ms=0.0,
        duplicate_key_count=0,
        invalid_code_count=0,
        out_of_partition_count=0,
        identity_failure_count=0,
        blank_name_count=0,
        empty_result=True,
        failed=True,
        failure_reason="source_access_error",
        failure_samples=(message,),
    )


def _target_audit(
    *,
    connection,
    lake_root: Path,
    plan: DcBoardDatePlan,
    layer: str,
) -> DcBoardTargetAudit:
    started = perf_counter()
    readiness = (
        _RAW_READINESS[plan.dataset]
        if layer == "raw"
        else _SILVER_READINESS[plan.dataset]
    )(
        connection=connection,
        lake_root=lake_root,
        expected_trade_dates=plan.expected_trade_dates,
        registered_trade_days=plan.expected_trade_dates,
    )
    statuses = readiness.statuses_by_trade_date
    missing = tuple(date_key for date_key, status in statuses.items() if not status.materialized)
    invalid = tuple(date_key for date_key, status in statuses.items() if status.materialized and not status.checks_passed)
    existing_paths = tuple(
        (
            _DATASET_SPECS[plan.dataset].raw_path_builder(lake_root, date_key)
            if layer == "raw"
            else _DATASET_SPECS[plan.dataset].silver_path_builder(lake_root, date_key)
        )
        for date_key in plan.expected_trade_dates
        if (
            _DATASET_SPECS[plan.dataset].raw_path_builder(lake_root, date_key)
            if layer == "raw"
            else _DATASET_SPECS[plan.dataset].silver_path_builder(lake_root, date_key)
        ).exists()
    )
    reasons = tuple(
        sorted(
            {
                reason
                for date_key in invalid
                for reason in statuses[date_key].summary.get("failed_rules", ())
            }
        )
    )
    return DcBoardTargetAudit(
        layer=layer,
        dataset=plan.dataset,
        expected_count=len(plan.expected_trade_dates),
        missing_count=len(missing),
        valid_existing_count=len(plan.expected_trade_dates) - len(missing) - len(invalid),
        invalid_existing_count=len(invalid),
        scanned_file_count=readiness.scanned_file_count,
        existing_bytes=sum(path.stat().st_size for path in existing_paths),
        invalid_trade_dates=invalid,
        invalid_reasons=reasons,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )


def run_dry_run(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    start_date: str | None = None,
    end_date: str | None = None,
    datasets: Sequence[str] = tuple(_DATASET_SPECS),
) -> DcBoardBootstrapDryRunReport:
    """Run the complete read-only plan and return a JSON-friendly report."""

    started = perf_counter()
    calendar_path = silver_trade_calendar_path(lake_root)
    with duckdb_resource.connect() as connection:
        plans = build_date_plans(
            connection=connection,
            calendar_path=calendar_path,
            start_date=start_date,
            end_date=end_date,
            datasets=datasets,
        )
        target_audits = [
            audit
            for plan in plans
            for layer in ("raw", "silver")
            for audit in (_target_audit(connection=connection, lake_root=lake_root, plan=plan, layer=layer),)
        ]
        source_audits: list[DcBoardSourceAudit] = []
        unavailable_sources: set[str] = set()
        for plan in plans:
            if plan.dataset == "dc_member":
                source_audits.extend(
                    audit_prod_member_partitions(
                        connection=connection,
                        prod_postgres=prod_postgres,
                        expected_trade_dates=plan.expected_trade_dates,
                    )
                )
                continue
            for trade_date in plan.expected_trade_dates:
                if plan.dataset in unavailable_sources:
                    source_audits.append(
                        _source_access_failure(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            source_method=_DATASET_SPECS[plan.dataset].source_method,
                            error=RuntimeError("source access was stopped after the first failure"),
                        )
                    )
                    continue
                try:
                    source_audits.append(
                        audit_tushare_partition(
                            connection=connection,
                            tushare=tushare,
                            dataset=plan.dataset,
                            trade_date=trade_date,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - report and fail closed per date.
                    unavailable_sources.add(plan.dataset)
                    source_audits.append(
                        _source_access_failure(
                            dataset=plan.dataset,
                            trade_date=trade_date,
                            source_method=_DATASET_SPECS[plan.dataset].source_method,
                            error=exc,
                        )
                    )
    stop_reasons = []
    if any(audit.invalid_existing_count for audit in target_audits):
        stop_reasons.append("existing_target_conflict")
    if any(audit.failed for audit in source_audits):
        stop_reasons.append("source_audit_failed")
    source_rows = {
        dataset: sum(audit.source_row_count for audit in source_audits if audit.dataset == dataset)
        for dataset in datasets
    }
    request_count = sum(audit.request_count for audit in source_audits)
    page_count = sum(audit.page_count for audit in source_audits)
    retry_count = sum(audit.retry_count for audit in source_audits)
    source_elapsed_ms_by_dataset = {}
    for dataset in datasets:
        dataset_audits = tuple(
            audit for audit in source_audits if audit.dataset == dataset
        )
        batch_elapsed_values = tuple(
            audit.batch_elapsed_ms
            for audit in dataset_audits
            if audit.batch_elapsed_ms is not None
        )
        source_elapsed_ms_by_dataset[dataset] = round(
            max(batch_elapsed_values)
            if batch_elapsed_values
            else sum(audit.elapsed_ms for audit in dataset_audits),
            3,
        )
    expected_raw = sum(len(plan.expected_trade_dates) for plan in plans)
    return DcBoardBootstrapDryRunReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        requested_start_date=start_date,
        requested_end_date=end_date,
        effective_end_date=max(plan.end_date for plan in plans),
        should_stop=bool(stop_reasons),
        stop_reason_codes=tuple(dict.fromkeys(stop_reasons)),
        date_plans=plans,
        source_audits=tuple(source_audits),
        target_audits=tuple(target_audits),
        expected_file_count=expected_raw * 2,
        expected_raw_file_count=expected_raw,
        expected_silver_file_count=expected_raw,
        source_row_count_by_dataset=source_rows,
        request_count=request_count,
        page_count=page_count,
        retry_count=retry_count,
        source_elapsed_ms_by_dataset=source_elapsed_ms_by_dataset,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )


def write_report(report: DcBoardBootstrapDryRunReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "DcBoardBootstrapDryRunReport",
    "DcBoardBootstrapPlanError",
    "DcBoardDatePlan",
    "DcBoardSourceAudit",
    "DcBoardTargetAudit",
    "audit_prod_member_partition",
    "audit_prod_member_partitions",
    "audit_tushare_partition",
    "build_date_plans",
    "run_dry_run",
    "write_report",
]
