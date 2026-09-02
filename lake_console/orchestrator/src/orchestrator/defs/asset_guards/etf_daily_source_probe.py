"""One-request publication probes for ETF daily source datasets."""

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from orchestrator.defs.resources import TushareResource
from orchestrator.defs.run_contracts.etf_daily import (
    FUND_ADJ_API_NAME,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_API_NAME,
    FUND_DAILY_SOURCE_COLUMNS,
    EtfDailySourceRequest,
    build_fund_adj_request,
    build_fund_daily_request,
    normalize_etf_daily_trade_date,
)


@dataclass(frozen=True, slots=True)
class EtfDailySourcePublication:
    api_name: str
    trade_date: str
    ready: bool
    reason_code: str
    row_count: int
    observed_columns: tuple[str, ...]
    elapsed_ms: float


def _probe_publication(
    *,
    tushare: TushareResource,
    trade_date: str,
    api_name: str,
    source_columns: tuple[str, ...],
    request_builder: Callable[[str, int], EtfDailySourceRequest],
) -> EtfDailySourcePublication:
    started_at = perf_counter()
    partition_key = normalize_etf_daily_trade_date(trade_date)
    request = request_builder(partition_key, 0)
    try:
        result = tushare.call(request.api_name, request.params, request.fields)
    except Exception:  # noqa: BLE001 - publication probes fail closed.
        return EtfDailySourcePublication(
            api_name=api_name,
            trade_date=partition_key,
            ready=False,
            reason_code="source_probe_request_failed",
            row_count=0,
            observed_columns=(),
            elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
        )

    reason_code = "ready"
    if not result.rows:
        reason_code = "source_not_published"
    elif tuple(result.columns) != source_columns:
        reason_code = "source_probe_schema_drift"
    else:
        expected_trade_date = partition_key.replace("-", "")
        seen_keys: set[tuple[object, object]] = set()
        invalid_key = False
        duplicate_key = False
        invalid_date = False
        for row in result.rows:
            code = row.get("ts_code")
            row_date = row.get("trade_date")
            if code is None or not str(code).strip() or row_date is None or not str(
                row_date
            ).strip():
                invalid_key = True
                continue
            key = (code, row_date)
            if key in seen_keys:
                duplicate_key = True
            seen_keys.add(key)
            if str(row_date).strip() != expected_trade_date:
                invalid_date = True
        if invalid_key:
            reason_code = "source_probe_invalid_key"
        elif duplicate_key:
            reason_code = "source_probe_duplicate_key"
        elif invalid_date:
            reason_code = "source_probe_date_mismatch"

    return EtfDailySourcePublication(
        api_name=api_name,
        trade_date=partition_key,
        ready=reason_code == "ready",
        reason_code=reason_code,
        row_count=len(result.rows),
        observed_columns=tuple(result.columns),
        elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
    )


def probe_fund_daily_publication(
    tushare: TushareResource,
    trade_date: str,
) -> EtfDailySourcePublication:
    return _probe_publication(
        tushare=tushare,
        trade_date=trade_date,
        api_name=FUND_DAILY_API_NAME,
        source_columns=FUND_DAILY_SOURCE_COLUMNS,
        request_builder=build_fund_daily_request,
    )


def probe_fund_adj_publication(
    tushare: TushareResource,
    trade_date: str,
) -> EtfDailySourcePublication:
    return _probe_publication(
        tushare=tushare,
        trade_date=trade_date,
        api_name=FUND_ADJ_API_NAME,
        source_columns=FUND_ADJ_SOURCE_COLUMNS,
        request_builder=build_fund_adj_request,
    )


__all__ = [
    "EtfDailySourcePublication",
    "probe_fund_adj_publication",
    "probe_fund_daily_publication",
]
