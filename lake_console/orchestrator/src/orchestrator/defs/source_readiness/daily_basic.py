"""Bounded Tushare requests; late successful responses are rejected locally."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Any

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DAILY_BASIC_PAGE_SIZE,
    DailyBasicValidationError,
    daily_basic_request_policy,
    daily_basic_trade_date,
)
from orchestrator.defs.resources import TushareResource
from orchestrator.defs.tushare_request_policy import execute_bounded_pages


@dataclass(frozen=True)
class DailyBasicSourceStatus:
    ready: bool
    reason: str
    row_count: int = 0
    code_count: int = 0
    missing_count: int = 0
    extra_count: int = 0
    missing_samples: tuple[str, ...] = ()
    request_count: int = 0
    elapsed_ms: float = 0


def fetch_daily_basic_pages(
    *,
    tushare: TushareResource,
    trade_date: str,
    fields: Sequence[str],
    consume_page: Callable[[int, Sequence[Mapping[str, Any]]], None],
    clock=perf_counter,
    sleep_fn=sleep,
):
    day = daily_basic_trade_date(trade_date).replace("-", "")
    policy = daily_basic_request_policy()
    started = clock()

    def guard():
        if clock() - started >= policy.max_elapsed_seconds:
            raise DailyBasicValidationError(
                "request_budget_exceeded：超过60秒，不接收该响应"
            )

    def request(offset):
        guard()
        result = tushare.call(
            "daily_basic",
            {"trade_date": day, "limit": DAILY_BASIC_PAGE_SIZE, "offset": offset},
            fields,
        )
        guard()
        if (
            tuple(result.columns) != tuple(fields)
            or len(result.rows) > DAILY_BASIC_PAGE_SIZE
        ):
            raise DailyBasicValidationError("source_schema_or_page_size")
        return result

    def key(row):
        if set(row) != set(fields):
            raise DailyBasicValidationError("source_row_schema")
        code = row.get("ts_code")
        if not isinstance(code, str) or not code.strip() or code != code.strip():
            raise DailyBasicValidationError("source_invalid_code")
        if row.get("trade_date") != day:
            raise DailyBasicValidationError("source_invalid_date")
        return code, day

    def consume(offset, rows):
        guard()
        consume_page(offset, rows)

    result = execute_bounded_pages(
        request_page=request,
        extract_rows=lambda response: response.rows,
        page_size=DAILY_BASIC_PAGE_SIZE,
        policy=policy,
        scope=f"daily_basic:{trade_date}",
        row_key=key,
        consume_page=consume,
        retain_rows=False,
        clock=clock,
        sleep_fn=sleep_fn,
    )
    guard()
    if not result.completed:
        raise DailyBasicValidationError(
            result.blocked_reason or "source_request_failed"
        )
    return result


def probe_daily_basic_for_trade_date(
    *,
    tushare: TushareResource,
    trade_date: str,
    expected_codes: Sequence[str],
    clock=perf_counter,
    sleep_fn=sleep,
) -> DailyBasicSourceStatus:
    expected = set(expected_codes)
    if not expected:
        return DailyBasicSourceStatus(False, "empty_upstream_codes")
    codes: set[str] = set()

    def consume(_offset, rows):
        codes.update(row["ts_code"] for row in rows)

    try:
        result = fetch_daily_basic_pages(
            tushare=tushare,
            trade_date=trade_date,
            fields=DAILY_BASIC_FIELDS[:2],
            consume_page=consume,
            clock=clock,
            sleep_fn=sleep_fn,
        )
    except (DailyBasicValidationError, OSError) as error:
        return DailyBasicSourceStatus(False, str(error).split("：")[0])
    missing = sorted(expected - codes)
    return DailyBasicSourceStatus(
        not missing,
        "ready" if not missing else "source_missing_codes",
        len(codes),
        len(codes),
        len(missing),
        len(codes - expected),
        tuple(missing[:3]),
        result.request_count,
        result.elapsed_ms,
    )
