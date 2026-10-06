"""Full market moneyflow collection inside the writer, never a sensor probe."""

from dataclasses import dataclass
from time import perf_counter, sleep

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ELAPSED_SECONDS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_PAGE_SIZE,
    MONEYFLOW_REQUEST_TIMEOUT_SECONDS,
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    market_moneyflow_day,
    market_moneyflow_policy,
    market_moneyflow_row_hash,
    normalize_market_moneyflow_row,
)
from orchestrator.defs.tushare_request_policy import BoundedCodePageRequestSession


@dataclass(frozen=True)
class StableMarketMoneyflow:
    row: dict
    row_hash: str
    request_count: int
    retry_count: int
    elapsed_ms: float
    stability_gap_seconds: float


def collect_market_moneyflow(
    *,
    tushare,
    trade_date: str,
    on_first_round,
    clock=perf_counter,
    sleep_fn=sleep,
    check_cancel=lambda: None,
):
    market_moneyflow_day(trade_date)
    session = BoundedCodePageRequestSession(
        policy=market_moneyflow_policy(), clock=clock, sleep_fn=sleep_fn
    )

    def guard(*, before_request=False):
        check_cancel()
        required = MONEYFLOW_REQUEST_TIMEOUT_SECONDS if before_request else 0
        if session.elapsed_ms / 1000 + required >= MONEYFLOW_MAX_ELAPSED_SECONDS:
            raise MoneyflowContractError("request_budget_exceeded")

    def request(offset):
        guard(before_request=True)
        response = tushare.call(
            "moneyflow_mkt_dc",
            {
                "trade_date": trade_date.replace("-", ""),
                "limit": MONEYFLOW_PAGE_SIZE,
                "offset": offset,
            },
            MONEYFLOW_MKT_DC_FIELDS,
        )
        guard()
        if tuple(response.columns) != MONEYFLOW_MKT_DC_FIELDS:
            raise MoneyflowContractError("source_schema")
        if len(response.rows) > 1:
            raise MoneyflowContractError("market_row_count")
        return response

    first = None
    first_end = None
    for round_number in (1, 2):
        guard()
        if round_number == 2:
            while clock() - first_end < MONEYFLOW_STABILITY_SECONDS:
                guard()
                sleep_fn(min(1, MONEYFLOW_STABILITY_SECONDS - (clock() - first_end)))
        collected = []

        def consume(_offset, rows, collected=collected):
            guard()
            collected.extend(
                normalize_market_moneyflow_row(row, trade_date) for row in rows
            )

        result = session.execute_pages(
            request_page=request,
            extract_rows=lambda r: r.rows,
            page_size=MONEYFLOW_PAGE_SIZE,
            scope=f"moneyflow_mkt_dc:{round_number}",
            consume_page=consume,
            retain_rows=False,
        )
        guard()
        if not result.completed:
            raise MoneyflowContractError(
                result.blocked_reason or "source_request_failed"
            )
        if len(collected) != 1:
            raise MoneyflowContractError("source_pending")
        if round_number == 1:
            first = collected[0]
            first_end = clock()
            on_first_round(first)
        elif collected[0] != first:
            raise MoneyflowContractError("source_unstable")
    return StableMarketMoneyflow(
        first,
        market_moneyflow_row_hash(first),
        session.request_count,
        session.retry_count,
        session.elapsed_ms,
        clock() - first_end,
    )
