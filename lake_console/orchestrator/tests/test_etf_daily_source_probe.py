from collections.abc import Mapping, Sequence

import pytest

from orchestrator.defs.asset_guards.etf_daily_source_probe import (
    probe_fund_adj_publication,
    probe_fund_daily_publication,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.etf_daily import (
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
)

PARTITION = "2026-09-01"
SOURCE_DATE = "20260901"


def _daily_row(
    ts_code: str = "510330.SH",
    *,
    trade_date: str = SOURCE_DATE,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "pre_close": 4.0,
        "open": 4.0,
        "high": 4.02,
        "low": 3.99,
        "close": 4.01,
        "change": 0.01,
        "pct_chg": 0.25,
        "vol": 100.0,
        "amount": 400.0,
    }


class _FakeTushare:
    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        columns: tuple[str, ...],
        error: Exception | None = None,
    ) -> None:
        self.rows = [dict(row) for row in rows]
        self.columns = columns
        self.error = error
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):  # type: ignore[no-untyped-def]
        self.calls.append((api_name, dict(params), tuple(fields)))
        if self.error is not None:
            raise self.error
        return TushareResult(
            rows=list(self.rows),
            columns=self.columns,
            metadata={},
        )


def test_fund_daily_probe_uses_one_exact_request_and_does_not_filter_of() -> None:
    source = _FakeTushare(
        rows=[_daily_row("158008.OF")],
        columns=FUND_DAILY_SOURCE_COLUMNS,
    )

    publication = probe_fund_daily_publication(  # type: ignore[arg-type]
        source,
        PARTITION,
    )

    assert publication.ready is True
    assert publication.reason_code == "ready"
    assert publication.row_count == 1
    assert source.calls == [
        (
            "fund_daily",
            {"trade_date": SOURCE_DATE, "limit": 5_000, "offset": 0},
            FUND_DAILY_SOURCE_COLUMNS,
        )
    ]


def test_fund_adj_probe_never_requests_a_second_page_when_first_page_is_full() -> None:
    rows = [
        {
            "ts_code": f"{index:06d}.SH",
            "trade_date": SOURCE_DATE,
            "adj_factor": 1.0,
            "discount_rate": None,
        }
        for index in range(2_000)
    ]
    source = _FakeTushare(rows=rows, columns=FUND_ADJ_SOURCE_COLUMNS)

    publication = probe_fund_adj_publication(  # type: ignore[arg-type]
        source,
        PARTITION,
    )

    assert publication.ready is True
    assert publication.row_count == 2_000
    assert len(source.calls) == 1
    assert source.calls[0] == (
        "fund_adj",
        {"trade_date": SOURCE_DATE, "limit": 2_000, "offset": 0},
        FUND_ADJ_SOURCE_COLUMNS,
    )


@pytest.mark.parametrize(
    ("rows", "columns", "error", "reason_code"),
    [
        ([], FUND_DAILY_SOURCE_COLUMNS, None, "source_not_published"),
        (
            [_daily_row()],
            FUND_DAILY_SOURCE_COLUMNS[:-1],
            None,
            "source_probe_schema_drift",
        ),
        (
            [_daily_row(), _daily_row()],
            FUND_DAILY_SOURCE_COLUMNS,
            None,
            "source_probe_duplicate_key",
        ),
        (
            [_daily_row(trade_date="20260829")],
            FUND_DAILY_SOURCE_COLUMNS,
            None,
            "source_probe_date_mismatch",
        ),
        (
            [_daily_row(ts_code="")],
            FUND_DAILY_SOURCE_COLUMNS,
            None,
            "source_probe_invalid_key",
        ),
        (
            [],
            FUND_DAILY_SOURCE_COLUMNS,
            RuntimeError("unavailable"),
            "source_probe_request_failed",
        ),
    ],
)
def test_probe_failure_modes_are_fail_closed(
    rows: Sequence[Mapping[str, object]],
    columns: tuple[str, ...],
    error: Exception | None,
    reason_code: str,
) -> None:
    source = _FakeTushare(rows=rows, columns=columns, error=error)

    publication = probe_fund_daily_publication(  # type: ignore[arg-type]
        source,
        PARTITION,
    )

    assert publication.ready is False
    assert publication.reason_code == reason_code
    assert len(source.calls) == 1
