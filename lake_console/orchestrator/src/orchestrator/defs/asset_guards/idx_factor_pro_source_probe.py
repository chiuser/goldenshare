"""One-request same-day source probe for ``idx_factor_pro`` automation."""

from dataclasses import dataclass
from time import perf_counter

from orchestrator.defs.resources import TushareResource
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_PAGE_LIMIT,
    IDX_FACTOR_PRO_SOURCE_COLUMNS,
    active_idx_factor_pro_daily_codes,
    build_idx_factor_pro_daily_request,
    normalize_idx_factor_pro_trade_date,
)


@dataclass(frozen=True, slots=True)
class IdxFactorProSourceProbeResult:
    trade_date: str
    ready: bool
    reason_code: str
    expected_code_count: int
    returned_code_count: int
    source_row_count: int
    request_count: int
    retry_count: int
    elapsed_ms: float


def probe_idx_factor_pro_source(
    *,
    tushare: TushareResource,
    trade_date: str,
) -> IdxFactorProSourceProbeResult:
    """Prove current-date source completeness with exactly one bounded page."""

    started_at = perf_counter()
    partition_key = normalize_idx_factor_pro_trade_date(trade_date)
    request = build_idx_factor_pro_daily_request(partition_key, 0)
    result = tushare.call(request.api_name, request.params, request.fields)
    expected_codes = set(active_idx_factor_pro_daily_codes(partition_key))

    reason_code = "ready"
    returned_codes: set[str] = set()
    target_keys: set[tuple[str, str]] = set()
    duplicate_key = False
    invalid_target_date = False
    if tuple(result.columns) != IDX_FACTOR_PRO_SOURCE_COLUMNS:
        reason_code = "source_probe_schema_drift"
    else:
        target_date = partition_key.replace("-", "")
        for row in result.rows:
            code = str(row.get("ts_code", "")).strip().upper()
            if code not in expected_codes:
                continue
            row_date = str(row.get("trade_date", "")).strip().replace("-", "")
            if row_date != target_date:
                invalid_target_date = True
                continue
            key = (code, row_date)
            if key in target_keys:
                duplicate_key = True
            target_keys.add(key)
            returned_codes.add(code)
        if len(result.rows) >= IDX_FACTOR_PRO_PAGE_LIMIT:
            reason_code = "source_probe_page_full"
        elif invalid_target_date:
            reason_code = "source_probe_date_mismatch"
        elif duplicate_key:
            reason_code = "source_probe_duplicate_key"
        elif returned_codes != expected_codes:
            reason_code = "source_probe_incomplete"

    return IdxFactorProSourceProbeResult(
        trade_date=partition_key,
        ready=reason_code == "ready",
        reason_code=reason_code,
        expected_code_count=len(expected_codes),
        returned_code_count=len(returned_codes),
        source_row_count=len(result.rows),
        request_count=1,
        retry_count=0,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
    )


__all__ = ["IdxFactorProSourceProbeResult", "probe_idx_factor_pro_source"]
