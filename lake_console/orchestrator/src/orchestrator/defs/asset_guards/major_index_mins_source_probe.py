"""Bounded same-day source probe for major-index minute Raw automation."""

from dataclasses import dataclass

from orchestrator.defs.resources import TushareResource, TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_DAILY_CODES,
    MAJOR_INDEX_MINS_PAGE_LIMIT,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    normalize_major_index_mins_trade_date,
)
from orchestrator.defs.tushare_request_policy import (
    TushareRequestPolicy,
    execute_bounded_code_pages,
)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceProbeResult:
    trade_date: str
    ready: bool
    reason_code: str
    expected_code_count: int
    returned_code_count: int
    request_count: int
    retry_count: int
    elapsed_ms: float


def _extract_rows(result: TushareResult):
    if not result.rows and not result.columns:
        return ()
    if tuple(result.columns) != MAJOR_INDEX_MINS_SOURCE_COLUMNS:
        raise ValueError("source_probe_schema_drift")
    return tuple(dict(row) for row in result.rows)


def probe_major_index_mins_source(
    *,
    tushare: TushareResource,
    trade_date: str,
    request_policy: TushareRequestPolicy,
) -> MajorIndexMinsSourceProbeResult:
    """Probe one closing 1-minute bar for each continuously online index."""

    normalized_date = normalize_major_index_mins_trade_date(trade_date)
    probe_time = f"{normalized_date} 15:00:00"
    result = execute_bounded_code_pages(
        codes=MAJOR_INDEX_MINS_DAILY_CODES,
        request_page=lambda code, offset: tushare.call(
            "idx_mins",
            {
                "ts_code": code,
                "freq": "1min",
                "start_date": probe_time,
                "end_date": probe_time,
                "limit": MAJOR_INDEX_MINS_PAGE_LIMIT,
                "offset": offset,
            },
            MAJOR_INDEX_MINS_SOURCE_COLUMNS,
        ),
        extract_rows=_extract_rows,
        page_size=MAJOR_INDEX_MINS_PAGE_LIMIT,
        policy=request_policy,
        row_key=lambda row: (row.get("ts_code"), row.get("trade_time")),
    )
    returned_codes: set[str] = set()
    contract_failed = False
    for requested_code, rows in result.rows_by_code.items():
        for row in rows:
            code = str(row.get("ts_code", "")).strip().upper()
            frequency = str(row.get("freq", "")).strip()
            trade_time = str(row.get("trade_time", "")).strip()
            if (
                code != requested_code
                or frequency != "1min"
                or not trade_time.startswith(normalized_date)
                or not trade_time.endswith("15:00:00")
            ):
                contract_failed = True
                continue
            returned_codes.add(code)

    expected_codes = set(MAJOR_INDEX_MINS_DAILY_CODES)
    ready = (
        result.ready
        and not contract_failed
        and returned_codes == expected_codes
        and not result.empty_codes
    )
    if not result.ready:
        reason_code = "source_probe_request_failed"
    elif contract_failed:
        reason_code = "source_probe_contract_failed"
    elif returned_codes != expected_codes or result.empty_codes:
        reason_code = "source_probe_incomplete"
    else:
        reason_code = "ready"
    return MajorIndexMinsSourceProbeResult(
        trade_date=normalized_date,
        ready=ready,
        reason_code=reason_code,
        expected_code_count=len(expected_codes),
        returned_code_count=len(returned_codes),
        request_count=result.request_count,
        retry_count=result.retry_count,
        elapsed_ms=round(result.elapsed_ms, 3),
    )


__all__ = ["MajorIndexMinsSourceProbeResult", "probe_major_index_mins_source"]
