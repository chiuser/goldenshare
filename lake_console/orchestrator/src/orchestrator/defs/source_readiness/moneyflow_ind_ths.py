"""Stream two industry rounds through one bounded Tushare request session."""

from dataclasses import dataclass
from time import perf_counter, sleep

from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ELAPSED_SECONDS,
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MONEYFLOW_PAGE_SIZE,
    MONEYFLOW_REQUEST_TIMEOUT_SECONDS,
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
    market_moneyflow_day,
    market_moneyflow_policy,
    moneyflow_peak_rss_bytes,
)
from orchestrator.defs.run_contracts.moneyflow_ind_ths import MONEYFLOW_IND_THS_FIELDS
from orchestrator.defs.tushare_request_policy import BoundedCodePageRequestSession


@dataclass(frozen=True)
class IndustryMoneyflowCollection:
    row_count: int
    request_count: int
    retry_count: int
    elapsed_ms: float
    stability_gap_seconds: float
    peak_rss_bytes: int


def collect_industry_moneyflow(
    *,
    tushare,
    trade_date: str,
    consume_page,
    complete_round,
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
        assert_moneyflow_memory_budget()
        reserve = MONEYFLOW_REQUEST_TIMEOUT_SECONDS if before_request else 0
        if session.elapsed_ms / 1000 + reserve >= MONEYFLOW_MAX_ELAPSED_SECONDS:
            raise MoneyflowContractError("request_budget_exceeded")

    def request(offset):
        guard(before_request=True)
        response = tushare.call(
            "moneyflow_ind_ths",
            {
                "trade_date": trade_date.replace("-", ""),
                "limit": MONEYFLOW_PAGE_SIZE,
                "offset": offset,
            },
            MONEYFLOW_IND_THS_FIELDS,
        )
        guard()
        if tuple(response.columns) != MONEYFLOW_IND_THS_FIELDS:
            raise MoneyflowContractError("source_schema")
        if len(response.rows) > MONEYFLOW_PAGE_SIZE:
            raise MoneyflowContractError("source_page_size")
        return response

    first_end = None
    first_count = None
    gap = 0
    for round_number in (1, 2):
        guard()
        if round_number == 2:
            while clock() - first_end < MONEYFLOW_STABILITY_SECONDS:
                guard()
                sleep_fn(min(1, MONEYFLOW_STABILITY_SECONDS - (clock() - first_end)))
            gap = clock() - first_end
        round_count = [0]

        def consume(offset, rows, round_count=round_count, round_number=round_number):
            guard()
            round_count[0] += len(rows)
            if round_count[0] > MONEYFLOW_MAX_ROWS_PER_ROUND:
                raise MoneyflowContractError("source_row_budget")
            if rows:
                consume_page(round_number, offset, rows)
            guard()

        result = session.execute_pages(
            request_page=request,
            extract_rows=lambda r: r.rows,
            page_size=MONEYFLOW_PAGE_SIZE,
            scope=f"moneyflow_ind_ths:{round_number}",
            consume_page=consume,
            retain_rows=False,
        )
        guard()
        if not result.completed:
            raise MoneyflowContractError(
                f"{result.blocked_reason or 'source_request_failed'}:"
                f"{result.failed_pages[0].message if result.failed_pages else 'budget'}"
            )
        if round_count[0] == 0:
            raise MoneyflowContractError("source_pending")
        complete_round(round_number, round_count[0])
        guard()
        if round_number == 1:
            first_end = clock()
            first_count = round_count[0]
        elif round_count[0] != first_count:
            raise MoneyflowContractError("source_unstable")
    return IndustryMoneyflowCollection(
        first_count,
        session.request_count,
        session.retry_count,
        session.elapsed_ms,
        gap,
        moneyflow_peak_rss_bytes(),
    )
