"""Small, bounded source-availability probes for the board update sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from orchestrator.defs.assets.dc_board import _canonical_trade_date
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import raw_dc_index_path
from orchestrator.defs.resources import DuckDBResource, TushareResource, TushareResult
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_CATEGORIES,
    DC_DAILY_FIELDS,
    DC_INDEX_FIELDS,
    DC_INDEX_TYPES,
    DC_MEMBER_FIELDS,
)
from orchestrator.defs.tushare_request_policy import (
    BoundedCodeRequestResult,
    TushareRequestPolicy,
    execute_bounded_code_requests,
)


DC_BOARD_SOURCE_PROBE_MAX_MEMBER_CODES = 5
DC_BOARD_SOURCE_PROBE_MAX_REQUESTS = 5
DC_BOARD_SOURCE_PROBE_MAX_ELAPSED_SECONDS = 8.0

_PROBE_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=0,
    max_requests=DC_BOARD_SOURCE_PROBE_MAX_REQUESTS,
    max_elapsed_seconds=DC_BOARD_SOURCE_PROBE_MAX_ELAPSED_SECONDS,
)


@dataclass(frozen=True, slots=True)
class DcBoardSourceProbeResult:
    dataset: str
    trade_date: str
    ready: bool
    reason_code: str
    request_count: int
    retry_count: int
    elapsed_ms: float
    successful_count: int
    empty_count: int
    failed_count: int
    unattempted_count: int
    sample: tuple[dict[str, object], ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "trade_date": self.trade_date,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "successful_count": self.successful_count,
            "empty_count": self.empty_count,
            "failed_count": self.failed_count,
            "unattempted_count": self.unattempted_count,
            "sample_count": len(self.sample),
        }


def _rows(result: TushareResult, fields: Sequence[str]) -> Sequence[Mapping[str, object]]:
    if result.columns and tuple(result.columns) != tuple(fields):
        raise ValueError(
            f"source probe columns drifted: expected={tuple(fields)}, got={result.columns}"
        )
    return result.rows


def _request_outcome(
    *,
    dataset: str,
    trade_date: str,
    result: BoundedCodeRequestResult[TushareResult],
    sample: Sequence[dict[str, object]] = (),
    require_non_empty: bool = True,
) -> DcBoardSourceProbeResult:
    if result.budget_exceeded:
        reason_code = "source_request_budget_exceeded"
    elif result.failed_codes:
        reason_code = "source_probe_error"
    elif result.unattempted_codes:
        reason_code = "source_request_incomplete"
    elif require_non_empty and not result.successful_codes:
        reason_code = "source_probe_not_ready"
    else:
        reason_code = "ready"
    return DcBoardSourceProbeResult(
        dataset=dataset,
        trade_date=trade_date,
        ready=reason_code == "ready",
        reason_code=reason_code,
        request_count=result.request_count,
        retry_count=result.retry_count,
        elapsed_ms=result.elapsed_ms,
        successful_count=len(result.successful_codes),
        empty_count=len(result.empty_codes),
        failed_count=len(result.failed_codes),
        unattempted_count=len(result.unattempted_codes),
        sample=tuple(sample[:5]),
    )


def _validate_rows(
    *,
    rows_by_code: Mapping[str, Sequence[Mapping[str, object]]],
    code_kind: str,
    trade_date: str,
) -> tuple[dict[str, object], ...]:
    expected_raw_date = trade_date.replace("-", "")
    failures: list[dict[str, object]] = []
    for requested_code, rows in rows_by_code.items():
        for row in rows:
            observed_date = _canonical_trade_date(row.get("trade_date"))
            if observed_date != expected_raw_date:
                failures.append(
                    {
                        "requested_code": requested_code,
                        "observed_trade_date": observed_date,
                        "reason_code": "trade_date_mismatch",
                    }
                )
            if code_kind == "idx_type" and row.get("idx_type") != requested_code:
                failures.append(
                    {
                        "requested_code": requested_code,
                        "observed_idx_type": row.get("idx_type"),
                        "reason_code": "idx_type_mismatch",
                    }
                )
            if code_kind == "ts_code" and str(row.get("ts_code", "")).strip().upper() != requested_code:
                failures.append(
                    {
                        "requested_code": requested_code,
                        "observed_ts_code": row.get("ts_code"),
                        "reason_code": "ts_code_mismatch",
                    }
                )
    return tuple(failures[:5])


def probe_dc_index(
    *,
    tushare: TushareResource,
    trade_date: str,
) -> DcBoardSourceProbeResult:
    started_at = perf_counter()
    try:
        result = execute_bounded_code_requests(
            codes=DC_INDEX_TYPES,
            request=lambda idx_type: tushare.call(
                "dc_index",
                {
                    "trade_date": trade_date.replace("-", ""),
                    "idx_type": idx_type,
                    "limit": 1,
                    "offset": 0,
                },
                DC_INDEX_FIELDS,
            ),
            extract_rows=lambda response: _rows(response, DC_INDEX_FIELDS),
            policy=_PROBE_POLICY,
        )
        sample = _validate_rows(
            rows_by_code=result.rows_by_code,
            code_kind="idx_type",
            trade_date=trade_date,
        )
        if sample:
            return DcBoardSourceProbeResult(
                dataset="dc_index",
                trade_date=trade_date,
                ready=False,
                reason_code="source_probe_error",
                request_count=result.request_count,
                retry_count=result.retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                successful_count=len(result.successful_codes),
                empty_count=len(result.empty_codes),
                failed_count=len(result.failed_codes),
                unattempted_count=len(result.unattempted_codes),
                sample=sample,
            )
        return _request_outcome(
            dataset="dc_index",
            trade_date=trade_date,
            result=result,
            sample=sample,
        )
    except Exception as exc:  # noqa: BLE001 - probe must fail closed.
        return DcBoardSourceProbeResult(
            dataset="dc_index",
            trade_date=trade_date,
            ready=False,
            reason_code="source_probe_error",
            request_count=0,
            retry_count=0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            successful_count=0,
            empty_count=0,
            failed_count=1,
            unattempted_count=0,
            sample=({"error": str(exc)[:300]},),
        )


def probe_dc_daily(
    *,
    tushare: TushareResource,
    trade_date: str,
) -> DcBoardSourceProbeResult:
    started_at = perf_counter()
    try:
        result = execute_bounded_code_requests(
            codes=("trade_date",),
            request=lambda _scope: tushare.call(
                "dc_daily",
                {
                    "trade_date": trade_date.replace("-", ""),
                    "limit": 1,
                    "offset": 0,
                },
                DC_DAILY_FIELDS,
            ),
            extract_rows=lambda response: _rows(response, DC_DAILY_FIELDS),
            policy=_PROBE_POLICY,
        )
        sample = _validate_rows(
            rows_by_code=result.rows_by_code,
            code_kind="none",
            trade_date=trade_date,
        )
        if sample:
            return DcBoardSourceProbeResult(
                dataset="dc_daily",
                trade_date=trade_date,
                ready=False,
                reason_code="source_probe_error",
                request_count=result.request_count,
                retry_count=result.retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                successful_count=len(result.successful_codes),
                empty_count=len(result.empty_codes),
                failed_count=len(result.failed_codes),
                unattempted_count=len(result.unattempted_codes),
                sample=sample,
            )
        return _request_outcome(
            dataset="dc_daily",
            trade_date=trade_date,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001 - probe must fail closed.
        return DcBoardSourceProbeResult(
            dataset="dc_daily",
            trade_date=trade_date,
            ready=False,
            reason_code="source_probe_error",
            request_count=0,
            retry_count=0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            successful_count=0,
            empty_count=0,
            failed_count=1,
            unattempted_count=0,
            sample=({"error": str(exc)[:300]},),
        )


def _load_member_probe_codes(connection, path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    rows = connection.execute(
        f"""
        SELECT DISTINCT upper(trim(CAST(ts_code AS VARCHAR)))
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ORDER BY 1
        LIMIT {DC_BOARD_SOURCE_PROBE_MAX_MEMBER_CODES}
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def probe_dc_member(
    *,
    connection,
    lake_root: Path,
    tushare: TushareResource,
    trade_date: str,
) -> DcBoardSourceProbeResult:
    started_at = perf_counter()
    codes = _load_member_probe_codes(
        connection,
        raw_dc_index_path(lake_root, trade_date),
    )
    if not codes:
        return DcBoardSourceProbeResult(
            dataset="dc_member",
            trade_date=trade_date,
            ready=False,
            reason_code="source_probe_not_ready",
            request_count=0,
            retry_count=0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            successful_count=0,
            empty_count=0,
            failed_count=0,
            unattempted_count=0,
            sample=({"reason_code": "member_probe_codes_missing"},),
        )
    try:
        result = execute_bounded_code_requests(
            codes=codes,
            request=lambda ts_code: tushare.call(
                "dc_member",
                {
                    "trade_date": trade_date.replace("-", ""),
                    "ts_code": ts_code,
                    "limit": 1,
                    "offset": 0,
                },
                DC_MEMBER_FIELDS,
            ),
            extract_rows=lambda response: _rows(response, DC_MEMBER_FIELDS),
            policy=_PROBE_POLICY,
        )
        sample = _validate_rows(
            rows_by_code=result.rows_by_code,
            code_kind="ts_code",
            trade_date=trade_date,
        )
        if sample:
            return DcBoardSourceProbeResult(
                dataset="dc_member",
                trade_date=trade_date,
                ready=False,
                reason_code="source_probe_error",
                request_count=result.request_count,
                retry_count=result.retry_count,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                successful_count=len(result.successful_codes),
                empty_count=len(result.empty_codes),
                failed_count=len(result.failed_codes),
                unattempted_count=len(result.unattempted_codes),
                sample=sample,
            )
        return _request_outcome(
            dataset="dc_member",
            trade_date=trade_date,
            result=result,
            require_non_empty=True,
        )
    except Exception as exc:  # noqa: BLE001 - probe must fail closed.
        return DcBoardSourceProbeResult(
            dataset="dc_member",
            trade_date=trade_date,
            ready=False,
            reason_code="source_probe_error",
            request_count=0,
            retry_count=0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            successful_count=0,
            empty_count=0,
            failed_count=1,
            unattempted_count=0,
            sample=({"error": str(exc)[:300]},),
        )


__all__ = [
    "DC_BOARD_SOURCE_PROBE_MAX_ELAPSED_SECONDS",
    "DC_BOARD_SOURCE_PROBE_MAX_MEMBER_CODES",
    "DC_BOARD_SOURCE_PROBE_MAX_REQUESTS",
    "DcBoardSourceProbeResult",
    "probe_dc_daily",
    "probe_dc_index",
    "probe_dc_member",
]
