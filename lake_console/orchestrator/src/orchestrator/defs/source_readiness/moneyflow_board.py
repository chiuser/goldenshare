"""Stream two independent board rounds through one bounded Tushare request session."""

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
from orchestrator.defs.run_contracts.moneyflow_board import (
    board_fields,
    board_request_scopes,
)
from orchestrator.defs.tushare_request_policy import BoundedCodePageRequestSession


@dataclass(frozen=True)
class BoardMoneyflowCollection:
    row_count: int
    request_count: int
    retry_count: int
    elapsed_ms: float
    stability_gap_seconds: float
    peak_rss_bytes: int
    scope_row_counts: tuple[int, ...]


def collect_board_moneyflow(
    *,
    tushare,
    dataset: str,
    trade_date: str,
    consume_page,
    complete_round,
    clock=perf_counter,
    sleep_fn=sleep,
    check_cancel=lambda: None,
):
    fields = board_fields(dataset)
    scopes = board_request_scopes(dataset)
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

    def request(offset, content_type):
        guard(before_request=True)
        params = {
            "trade_date": trade_date.replace("-", ""),
            "limit": MONEYFLOW_PAGE_SIZE,
            "offset": offset,
        }
        if content_type is not None:
            params["content_type"] = content_type
        response = tushare.call(
            dataset,
            params,
            fields,
        )
        guard()
        if tuple(response.columns) != fields:
            raise MoneyflowContractError("source_schema")
        if len(response.rows) > MONEYFLOW_PAGE_SIZE:
            raise MoneyflowContractError("source_page_size")
        return response

    first_end = None
    first_count = None
    first_scope_counts = None
    gap = 0
    for round_number in (1, 2):
        guard()
        if round_number == 2:
            while clock() - first_end < MONEYFLOW_STABILITY_SECONDS:
                guard()
                sleep_fn(min(1, MONEYFLOW_STABILITY_SECONDS - (clock() - first_end)))
            gap = clock() - first_end
        round_count = [0]
        scope_counts = []
        for content_type in scopes:
            scope_count = [0]

            def consume(
                offset,
                rows,
                round_count=round_count,
                round_number=round_number,
                content_type=content_type,
                scope_count=scope_count,
            ):
                guard()
                round_count[0] += len(rows)
                scope_count[0] += len(rows)
                if round_count[0] > MONEYFLOW_MAX_ROWS_PER_ROUND:
                    raise MoneyflowContractError("source_row_budget")
                if rows:
                    consume_page(round_number, content_type, offset, rows)
                guard()

            result = session.execute_pages(
                request_page=lambda offset, content_type=content_type: request(
                    offset, content_type
                ),
                extract_rows=lambda r: r.rows,
                page_size=MONEYFLOW_PAGE_SIZE,
                scope=f"{dataset}:{round_number}:{content_type or 'all'}",
                consume_page=consume,
                retain_rows=False,
            )
            guard()
            if not result.completed:
                raise MoneyflowContractError(
                    f"{result.blocked_reason or 'source_request_failed'}:"
                    f"{result.failed_pages[0].message if result.failed_pages else 'budget'}"
                )
            if scope_count[0] == 0:
                raise MoneyflowContractError(f"source_pending:{content_type or 'all'}")
            scope_counts.append(scope_count[0])
        complete_round(round_number, round_count[0])
        guard()
        if round_number == 1:
            first_end = clock()
            first_count = round_count[0]
            first_scope_counts = tuple(scope_counts)
        elif round_count[0] != first_count:
            raise MoneyflowContractError("source_unstable")
    return BoardMoneyflowCollection(
        first_count,
        session.request_count,
        session.retry_count,
        session.elapsed_ms,
        gap,
        moneyflow_peak_rss_bytes(),
        first_scope_counts,
    )
