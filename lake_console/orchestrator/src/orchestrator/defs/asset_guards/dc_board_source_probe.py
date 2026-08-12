"""Prod reference closure and Tushare identity comparison for DC Raw writes."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from numbers import Real
from time import perf_counter

from orchestrator.defs.resources import (
    ProdPostgresResource,
    TushareResource,
    TushareResult,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_ELAPSED_MS,
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
    DC_DAILY_CATEGORIES,
    DC_DAILY_FIELDS,
    DC_DAILY_PAGE_LIMIT,
    DC_INDEX_FIELDS,
    DC_INDEX_PAGE_LIMIT,
    DC_INDEX_TYPES,
    DC_MEMBER_BACKOFF_BASE_SECONDS,
    DC_MEMBER_BACKOFF_MAX_SECONDS,
    DC_MEMBER_MAX_RETRIES,
    DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS,
    DcBoardProdReferenceSnapshot,
    build_dc_board_prod_reference_snapshot,
)
from orchestrator.defs.tushare_request_policy import (
    TushareRequestPolicy,
    execute_bounded_code_pages,
    execute_bounded_pages,
)

_RAW_TRADE_DATE_RE = re.compile(r"^\d{8}$")
_BOARD_CODE_RE = re.compile(r"^BK\d{4}\.DC$")
_STOCK_CODE_RE = re.compile(r"^\d{6}\.(SZ|SH|BJ)$")


class DcBoardReferenceValidationError(ValueError):
    """Raised when a prod reference or Tushare identity is not complete."""


@dataclass(frozen=True, slots=True)
class DcBoardProdReferenceResult:
    trade_date: str
    ready: bool
    reason_code: str
    snapshot: DcBoardProdReferenceSnapshot | None
    query_count: int
    elapsed_ms: float
    invalid_key_count: int = 0
    duplicate_key_count: int = 0
    error: str | None = None

    def to_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "query_count": self.query_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "invalid_key_count": self.invalid_key_count,
            "duplicate_key_count": self.duplicate_key_count,
        }
        if self.snapshot is not None:
            summary.update(self.snapshot.compact_summary())
        if self.error:
            summary["error"] = self.error[:300]
        return summary


@dataclass(frozen=True, slots=True)
class DcBoardTushareReferenceComparison:
    trade_date: str
    ready: bool
    reason_code: str
    request_count: int
    page_count: int
    retry_count: int
    elapsed_ms: float
    index_rows_by_type: Mapping[str, tuple[dict[str, object], ...]]
    daily_rows: tuple[dict[str, object], ...]
    index_missing_count: int = 0
    index_extra_count: int = 0
    daily_missing_count: int = 0
    daily_extra_count: int = 0
    error: str | None = None

    def to_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {
            "trade_date": self.trade_date,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "request_count": self.request_count,
            "page_count": self.page_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "index_row_count": sum(len(rows) for rows in self.index_rows_by_type.values()),
            "daily_row_count": len(self.daily_rows),
            "index_missing_count": self.index_missing_count,
            "index_extra_count": self.index_extra_count,
            "daily_missing_count": self.daily_missing_count,
            "daily_extra_count": self.daily_extra_count,
        }
        if self.error:
            summary["error"] = self.error[:300]
        return summary


def build_dc_board_request_policy() -> TushareRequestPolicy:
    """Return the single bounded Tushare request budget for one DC partition."""

    return TushareRequestPolicy(
        minimum_interval_seconds=DC_MEMBER_MIN_REQUEST_INTERVAL_SECONDS,
        max_retries=DC_MEMBER_MAX_RETRIES,
        backoff_base_seconds=DC_MEMBER_BACKOFF_BASE_SECONDS,
        max_backoff_seconds=DC_MEMBER_BACKOFF_MAX_SECONDS,
        max_requests=DC_BOARD_MAX_REQUESTS_PER_PARTITION,
        max_elapsed_seconds=DC_BOARD_MAX_ELAPSED_MS / 1000,
    )


def canonical_raw_trade_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")
    return compact if _RAW_TRADE_DATE_RE.fullmatch(compact) else text


def normalize_tushare_rows(
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> tuple[dict[str, object], ...]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized: dict[str, object] = {}
        for field in fields:
            value = row.get(field)
            if isinstance(value, Real) and not isinstance(value, bool) and math.isnan(value):
                value = None
            normalized[field] = value
        normalized["trade_date"] = canonical_raw_trade_date(normalized.get("trade_date"))
        normalized_rows.append(normalized)
    return tuple(normalized_rows)


def _require_response_columns(result: TushareResult, fields: Sequence[str]) -> None:
    if result.columns and tuple(result.columns) != tuple(fields):
        raise DcBoardReferenceValidationError(
            f"Tushare response columns drifted: expected {tuple(fields)}, got {result.columns}."
        )


def _tushare_rows(result: TushareResult, fields: Sequence[str]) -> tuple[dict[str, object], ...]:
    _require_response_columns(result, fields)
    return normalize_tushare_rows(result.rows, fields)


def _normalize_identity_value(value: object) -> str:
    return str(value or "").strip().upper()


def _normalized_identity(rows: Sequence[Mapping[str, object]], identity_fields: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (_normalize_identity_value(row.get(identity_fields[0])), _normalize_identity_value(row.get(identity_fields[1])))
            for row in rows
        )
    )


def _identity_diff(
    expected: Sequence[tuple[str, str]],
    observed: Sequence[tuple[str, str]],
) -> tuple[int, int]:
    expected_set = set(expected)
    observed_set = set(observed)
    return len(expected_set - observed_set), len(observed_set - expected_set)


def _validate_identity_rows(
    *,
    rows: Sequence[Mapping[str, object]],
    trade_date: str,
    kind: str,
) -> None:
    expected_raw_trade_date = trade_date.replace("-", "")
    observed_dates = {canonical_raw_trade_date(row.get("trade_date")) for row in rows}
    if observed_dates != {expected_raw_trade_date}:
        raise DcBoardReferenceValidationError(
            f"{kind} Tushare rows contain a mismatched trade_date for {trade_date}."
        )

    if kind == "dc_index":
        identities = _normalized_identity(rows, ("idx_type", "ts_code"))
        if any(
            idx_type not in DC_INDEX_TYPES or not _BOARD_CODE_RE.fullmatch(ts_code)
            for idx_type, ts_code in identities
        ):
            raise DcBoardReferenceValidationError("dc_index Tushare rows contain an invalid identity.")
    elif kind == "dc_daily":
        identities = _normalized_identity(rows, ("category", "ts_code"))
        if any(
            category not in DC_DAILY_CATEGORIES or not _BOARD_CODE_RE.fullmatch(ts_code)
            for category, ts_code in identities
        ):
            raise DcBoardReferenceValidationError("dc_daily Tushare rows contain an invalid identity.")
    else:
        raise ValueError(f"unsupported DC identity kind: {kind}")
    if len(identities) != len(set(identities)):
        raise DcBoardReferenceValidationError(f"{kind} Tushare rows contain duplicate identities.")


def load_prod_dc_board_reference(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
) -> DcBoardProdReferenceResult:
    """Read exactly three prod identity queries and reject a non-closed snapshot."""

    started_at = perf_counter()
    try:
        partition_date = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(f"trade_date must be ISO YYYY-MM-DD: {trade_date!r}") from exc

    query_count = 0
    try:
        with (
            prod_postgres.connect_readonly_transaction() as connection,
            connection.cursor() as cursor,
        ):
            query_count += 1
            cursor.execute(
                """
                SELECT idx_type, ts_code
                FROM core_serving.dc_index
                WHERE trade_date = %s
                ORDER BY idx_type, ts_code
                """,
                (partition_date,),
            )
            index_identity = tuple(
                (_normalize_identity_value(idx_type), _normalize_identity_value(ts_code))
                for idx_type, ts_code in cursor.fetchall()
            )
            query_count += 1
            cursor.execute(
                """
                SELECT category, ts_code
                FROM core_serving.dc_daily
                WHERE trade_date = %s
                ORDER BY category, ts_code
                """,
                (partition_date,),
            )
            daily_identity = tuple(
                (_normalize_identity_value(category), _normalize_identity_value(ts_code))
                for category, ts_code in cursor.fetchall()
            )
            query_count += 1
            cursor.execute(
                """
                WITH scoped AS (
                    SELECT
                        upper(trim(ts_code)) AS ts_code,
                        upper(trim(con_code)) AS con_code
                    FROM core_serving.dc_member
                    WHERE trade_date = %s
                ), duplicate_pairs AS (
                    SELECT ts_code, con_code
                    FROM scoped
                    GROUP BY ts_code, con_code
                    HAVING count(*) > 1
                )
                SELECT
                    count(*) AS member_row_count,
                    count(*) FILTER (
                        WHERE ts_code IS NULL OR ts_code = ''
                           OR con_code IS NULL OR con_code = ''
                    ) AS invalid_key_count,
                    (SELECT count(*) FROM duplicate_pairs) AS duplicate_key_count,
                    coalesce(array_agg(DISTINCT ts_code ORDER BY ts_code)
                        FILTER (WHERE ts_code IS NOT NULL AND ts_code <> ''), ARRAY[]::text[])
                        AS member_codes
                FROM scoped
                """,
                (partition_date,),
            )
            member_row_count, invalid_key_count, duplicate_key_count, member_codes = (
                cursor.fetchone()
            )
    except Exception as exc:  # noqa: BLE001 - source readiness must fail closed.
        return DcBoardProdReferenceResult(
            trade_date=trade_date,
            ready=False,
            reason_code="prod_reference_unavailable",
            snapshot=None,
            query_count=query_count,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=str(exc),
        )

    normalized_member_codes = tuple(_normalize_identity_value(code) for code in member_codes)
    invalid_key_count = int(invalid_key_count or 0)
    duplicate_key_count = int(duplicate_key_count or 0)
    invalid_identity = (
        not index_identity
        or not daily_identity
        or not normalized_member_codes
        or {idx_type for idx_type, _ in index_identity} != set(DC_INDEX_TYPES)
        or {category for category, _ in daily_identity} != set(DC_DAILY_CATEGORIES)
        or any(
            idx_type not in DC_INDEX_TYPES or not _BOARD_CODE_RE.fullmatch(ts_code)
            for idx_type, ts_code in index_identity
        )
        or any(
            category not in DC_DAILY_CATEGORIES or not _BOARD_CODE_RE.fullmatch(ts_code)
            for category, ts_code in daily_identity
        )
        or any(not _BOARD_CODE_RE.fullmatch(code) for code in normalized_member_codes)
    )
    duplicate_identity = (
        len(index_identity) != len(set(index_identity))
        or len(daily_identity) != len(set(daily_identity))
        or len(normalized_member_codes) != len(set(normalized_member_codes))
    )
    index_code_set = {ts_code for _, ts_code in index_identity}
    daily_code_set = {ts_code for _, ts_code in daily_identity}
    member_code_set = set(normalized_member_codes)
    closed = (
        not invalid_identity
        and not duplicate_identity
        and invalid_key_count == 0
        and duplicate_key_count == 0
        and index_code_set.issubset(daily_code_set)
        and member_code_set.issubset(index_code_set)
    )
    if not closed:
        return DcBoardProdReferenceResult(
            trade_date=trade_date,
            ready=False,
            reason_code="prod_reference_not_closed",
            snapshot=None,
            query_count=3,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            invalid_key_count=invalid_key_count + int(invalid_identity),
            duplicate_key_count=duplicate_key_count + int(duplicate_identity),
        )
    snapshot = build_dc_board_prod_reference_snapshot(
        trade_date=trade_date,
        index_identity=index_identity,
        daily_identity=daily_identity,
        member_codes=normalized_member_codes,
        member_row_count=int(member_row_count or 0),
    )
    return DcBoardProdReferenceResult(
        trade_date=trade_date,
        ready=True,
        reason_code="ready",
        snapshot=snapshot,
        query_count=3,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def require_closed_prod_dc_board_reference(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
) -> DcBoardProdReferenceSnapshot:
    result = load_prod_dc_board_reference(prod_postgres=prod_postgres, trade_date=trade_date)
    if not result.ready or result.snapshot is None:
        raise DcBoardReferenceValidationError(
            f"prod DC reference is not closed for {trade_date}: {result.to_summary()}"
        )
    return result.snapshot


def compare_tushare_index_and_daily_to_reference(
    *,
    tushare: TushareResource,
    trade_date: str,
    reference: DcBoardProdReferenceSnapshot,
    policy: TushareRequestPolicy | None = None,
) -> DcBoardTushareReferenceComparison:
    """Fetch all index and daily rows once, then compare identities to prod."""

    if reference.trade_date != trade_date:
        raise ValueError("reference trade_date must equal the requested Tushare trade_date.")
    started_at = perf_counter()
    effective_policy = policy or build_dc_board_request_policy()
    index_result = None
    daily_result = None
    try:
        index_result = execute_bounded_code_pages(
            codes=DC_INDEX_TYPES,
            request_page=lambda idx_type, offset: tushare.call(
                "dc_index",
                {
                    "trade_date": trade_date.replace("-", ""),
                    "idx_type": idx_type,
                    "limit": DC_INDEX_PAGE_LIMIT,
                    "offset": offset,
                },
                DC_INDEX_FIELDS,
            ),
            extract_rows=lambda response: _tushare_rows(response, DC_INDEX_FIELDS),
            page_size=DC_INDEX_PAGE_LIMIT,
            policy=effective_policy,
            row_key=lambda row: (row.get("idx_type"), row.get("ts_code"), row.get("trade_date")),
        )
        if not index_result.ready:
            if index_result.budget_exceeded:
                reason_code = "source_request_budget_exceeded"
            elif index_result.failed_codes:
                reason_code = "source_request_error"
            else:
                reason_code = "source_request_incomplete"
            return DcBoardTushareReferenceComparison(
                trade_date=trade_date,
                ready=False,
                reason_code=reason_code,
                request_count=index_result.request_count,
                page_count=sum(index_result.page_counts.values()),
                retry_count=index_result.retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                index_rows_by_type={},
                daily_rows=(),
                error=str(index_result.to_details(max_failure_samples=3)),
            )
        index_rows_by_type = {
            idx_type: tuple(index_result.rows_by_code.get(idx_type, ()))
            for idx_type in DC_INDEX_TYPES
        }
        index_rows = tuple(row for rows in index_rows_by_type.values() for row in rows)
        _validate_identity_rows(rows=index_rows, trade_date=trade_date, kind="dc_index")

        remaining_request_budget = effective_policy.max_requests - index_result.request_count
        remaining_elapsed_seconds = (
            effective_policy.max_elapsed_seconds - (index_result.elapsed_ms / 1000)
        )
        if remaining_request_budget <= 0 or remaining_elapsed_seconds <= 0:
            return DcBoardTushareReferenceComparison(
                trade_date=trade_date,
                ready=False,
                reason_code="source_request_budget_exceeded",
                request_count=index_result.request_count,
                page_count=sum(index_result.page_counts.values()),
                retry_count=index_result.retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                index_rows_by_type=index_rows_by_type,
                daily_rows=(),
                error="dc_index exhausted the shared dc_index/dc_daily request budget.",
            )
        daily_policy = replace(
            effective_policy,
            max_requests=remaining_request_budget,
            max_elapsed_seconds=remaining_elapsed_seconds,
        )

        daily_result = execute_bounded_pages(
            request_page=lambda offset: tushare.call(
                "dc_daily",
                {
                    "trade_date": trade_date.replace("-", ""),
                    "limit": DC_DAILY_PAGE_LIMIT,
                    "offset": offset,
                },
                DC_DAILY_FIELDS,
            ),
            extract_rows=lambda response: _tushare_rows(response, DC_DAILY_FIELDS),
            page_size=DC_DAILY_PAGE_LIMIT,
            policy=daily_policy,
            scope=f"dc_daily:{trade_date}",
            row_key=lambda row: (row.get("category"), row.get("ts_code"), row.get("trade_date")),
        )
        request_count = index_result.request_count + daily_result.request_count
        retry_count = index_result.retry_count + daily_result.retry_count
        page_count = sum(index_result.page_counts.values()) + daily_result.page_count
        if not daily_result.ready:
            if daily_result.budget_exceeded:
                reason_code = "source_request_budget_exceeded"
            elif daily_result.failed_pages:
                reason_code = "source_request_error"
            else:
                reason_code = "source_request_incomplete"
            return DcBoardTushareReferenceComparison(
                trade_date=trade_date,
                ready=False,
                reason_code=reason_code,
                request_count=request_count,
                page_count=page_count,
                retry_count=retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                index_rows_by_type=index_rows_by_type,
                daily_rows=(),
                error=str(daily_result.to_details(max_failure_samples=3)),
            )
        daily_rows = tuple(daily_result.rows)
        _validate_identity_rows(rows=daily_rows, trade_date=trade_date, kind="dc_daily")

        observed_index_identity = _normalized_identity(index_rows, ("idx_type", "ts_code"))
        observed_daily_identity = _normalized_identity(daily_rows, ("category", "ts_code"))
        index_missing_count, index_extra_count = _identity_diff(reference.index_identity, observed_index_identity)
        daily_missing_count, daily_extra_count = _identity_diff(reference.daily_identity, observed_daily_identity)
        ready = not any((index_missing_count, index_extra_count, daily_missing_count, daily_extra_count))
        return DcBoardTushareReferenceComparison(
            trade_date=trade_date,
            ready=ready,
            reason_code="ready" if ready else "tushare_reference_mismatch",
            request_count=request_count,
            page_count=page_count,
            retry_count=retry_count,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            index_rows_by_type=index_rows_by_type,
            daily_rows=daily_rows,
            index_missing_count=index_missing_count,
            index_extra_count=index_extra_count,
            daily_missing_count=daily_missing_count,
            daily_extra_count=daily_extra_count,
        )
    except Exception as exc:  # noqa: BLE001 - Tushare source validation must fail closed.
        index_request_count = index_result.request_count if index_result is not None else 0
        index_page_count = (
            sum(index_result.page_counts.values()) if index_result is not None else 0
        )
        index_retry_count = index_result.retry_count if index_result is not None else 0
        daily_request_count = daily_result.request_count if daily_result is not None else 0
        daily_page_count = daily_result.page_count if daily_result is not None else 0
        daily_retry_count = daily_result.retry_count if daily_result is not None else 0
        return DcBoardTushareReferenceComparison(
            trade_date=trade_date,
            ready=False,
            reason_code="source_request_error",
            request_count=index_request_count + daily_request_count,
            page_count=index_page_count + daily_page_count,
            retry_count=index_retry_count + daily_retry_count,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            index_rows_by_type={},
            daily_rows=(),
            error=str(exc),
        )


def require_tushare_index_and_daily_reference_match(
    *,
    tushare: TushareResource,
    trade_date: str,
    reference: DcBoardProdReferenceSnapshot,
    policy: TushareRequestPolicy | None = None,
) -> DcBoardTushareReferenceComparison:
    comparison = compare_tushare_index_and_daily_to_reference(
        tushare=tushare,
        trade_date=trade_date,
        reference=reference,
        policy=policy,
    )
    if not comparison.ready:
        raise DcBoardReferenceValidationError(
            f"Tushare DC source does not match prod reference for {trade_date}: {comparison.to_summary()}"
        )
    return comparison


def assert_dc_daily_rows_match_reference(
    *,
    rows: Sequence[Mapping[str, object]],
    trade_date: str,
    reference: DcBoardProdReferenceSnapshot,
) -> None:
    """Reject daily rows that do not exactly match the frozen prod identity."""

    _validate_identity_rows(rows=rows, trade_date=trade_date, kind="dc_daily")
    missing_count, extra_count = _identity_diff(
        reference.daily_identity,
        _normalized_identity(rows, ("category", "ts_code")),
    )
    if missing_count or extra_count:
        raise DcBoardReferenceValidationError(
            "dc_daily Tushare identity differs from fresh prod reference: "
            f"missing_count={missing_count}, extra_count={extra_count}."
        )


def load_prod_dc_member_pairs(
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
) -> tuple[tuple[str, str], ...]:
    """Read exact prod member pairs for a writer-only DuckDB set comparison."""

    partition_date = date.fromisoformat(trade_date)
    with (
        prod_postgres.connect_readonly_transaction() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT upper(trim(ts_code)), upper(trim(con_code))
            FROM core_serving.dc_member
            WHERE trade_date = %s
            ORDER BY upper(trim(ts_code)), upper(trim(con_code))
            """,
            (partition_date,),
        )
        pairs = tuple(
            (_normalize_identity_value(ts_code), _normalize_identity_value(con_code))
            for ts_code, con_code in cursor.fetchall()
        )
    if (
        not pairs
        or len(pairs) != len(set(pairs))
        or any(
            not _BOARD_CODE_RE.fullmatch(ts_code) or not _STOCK_CODE_RE.fullmatch(con_code)
            for ts_code, con_code in pairs
        )
    ):
        raise DcBoardReferenceValidationError(
            f"prod dc_member pair reference is invalid for {trade_date}."
        )
    return pairs


__all__ = [
    "DcBoardProdReferenceResult",
    "DcBoardProdReferenceSnapshot",
    "DcBoardReferenceValidationError",
    "DcBoardTushareReferenceComparison",
    "assert_dc_daily_rows_match_reference",
    "build_dc_board_request_policy",
    "canonical_raw_trade_date",
    "compare_tushare_index_and_daily_to_reference",
    "load_prod_dc_board_reference",
    "load_prod_dc_member_pairs",
    "normalize_tushare_rows",
    "require_closed_prod_dc_board_reference",
    "require_tushare_index_and_daily_reference_match",
]
