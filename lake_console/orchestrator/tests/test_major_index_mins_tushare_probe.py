from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.defs.io.major_index_mins_raw_writer import (
    MajorIndexMinsFetchError,
    fetch_major_index_mins_window,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class _FakeTushare:
    def __init__(self, rows_by_code_offset):
        self.rows_by_code_offset = rows_by_code_offset
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        rows = self.rows_by_code_offset.get((params["ts_code"], params["offset"]), [])
        return TushareResult(rows=list(rows), columns=tuple(fields), metadata={})


def _policy(*, max_requests: int = 20) -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=max_requests,
        max_elapsed_seconds=30.0,
    )


def _row(
    code: str,
    trade_time: str,
    *,
    freq: str = "1min",
) -> dict[str, object]:
    return {
        "ts_code": code,
        "freq": freq,
        "trade_time": trade_time,
        "open": 1.0,
        "close": 1.1,
        "high": 1.2,
        "low": 0.9,
        "vol": 10.0,
        "amount": 11.0,
        "exchange": "XSHG",
        "vwap": 1.05,
    }


def test_fetch_uses_explicit_fields_and_strict_offsets() -> None:
    fake = _FakeTushare(
        {
            ("000001.SH", 0): [
                _row("000001.SH", "2026-08-04 09:31:00"),
                _row("000001.SH", "2026-08-04 09:32:00"),
            ],
            ("000001.SH", 2): [_row("000001.SH", "2026-08-04 09:33:00")],
            ("000300.SH", 0): [_row("000300.SH", "2026-08-04 09:31:00")],
        }
    )
    with patch(
        "orchestrator.defs.io.major_index_mins_raw_writer.MAJOR_INDEX_MINS_PAGE_LIMIT",
        2,
    ):
        result = fetch_major_index_mins_window(
            tushare=fake,
            ts_codes=("000001.SH", "000300.SH"),
            source_freq="1min",
            start_datetime="2026-08-04 09:30:00",
            end_datetime="2026-08-04 15:00:00",
            request_policy=_policy(),
        )

    assert [(call[1]["ts_code"], call[1]["offset"]) for call in fake.calls] == [
        ("000001.SH", 0),
        ("000001.SH", 2),
        ("000300.SH", 0),
    ]
    assert all(call[0] == "idx_mins" for call in fake.calls)
    assert all(call[2] == MAJOR_INDEX_MINS_SOURCE_COLUMNS for call in fake.calls)
    assert all(call[1]["limit"] == 2 for call in fake.calls)
    assert all("fields" not in call[1] for call in fake.calls)
    assert result.request_count == 3
    assert result.page_count == 3
    assert len(result.rows) == 4


def test_fetch_fails_closed_for_empty_expected_code() -> None:
    with pytest.raises(MajorIndexMinsFetchError, match="source_empty"):
        fetch_major_index_mins_window(
            tushare=_FakeTushare({}),
            ts_codes=("000001.SH",),
            source_freq="1min",
            start_datetime="2026-08-04 09:30:00",
            end_datetime="2026-08-04 15:00:00",
            request_policy=_policy(),
        )


def test_fetch_fails_closed_on_schema_drift() -> None:
    class _Drifted(_FakeTushare):
        def call(self, api_name, params, fields):
            self.calls.append((api_name, dict(params), tuple(fields)))
            return TushareResult(
                rows=[_row(params["ts_code"], "2026-08-04 09:31:00")],
                columns=("ts_code",),
                metadata={},
            )

    with pytest.raises(MajorIndexMinsFetchError, match="schema_drift"):
        fetch_major_index_mins_window(
            tushare=_Drifted({}),
            ts_codes=("000001.SH",),
            source_freq="1min",
            start_datetime="2026-08-04 09:30:00",
            end_datetime="2026-08-04 15:00:00",
            request_policy=_policy(),
        )


def test_fetch_fails_closed_on_duplicate_rows_across_pages() -> None:
    duplicate = _row("000001.SH", "2026-08-04 09:31:00")
    fake = _FakeTushare(
        {
            ("000001.SH", 0): [duplicate],
            ("000001.SH", 1): [duplicate],
        }
    )
    with patch(
        "orchestrator.defs.io.major_index_mins_raw_writer.MAJOR_INDEX_MINS_PAGE_LIMIT",
        1,
    ), pytest.raises(MajorIndexMinsFetchError, match="duplicate_key"):
        fetch_major_index_mins_window(
            tushare=fake,
            ts_codes=("000001.SH",),
            source_freq="1min",
            start_datetime="2026-08-04 09:30:00",
            end_datetime="2026-08-04 15:00:00",
            request_policy=_policy(),
        )


def test_fetch_rejects_unknown_code_frequency_and_invalid_window() -> None:
    for kwargs, match in (
        ({"ts_codes": ("UNKNOWN",)}, "unsupported code"),
        ({"source_freq": "90min"}, "unsupported source frequency"),
        (
            {
                "start_datetime": "2026-08-04 15:00:00",
                "end_datetime": "2026-08-04 09:30:00",
            },
            "start_datetime",
        ),
    ):
        arguments = {
            "tushare": _FakeTushare({}),
            "ts_codes": ("000001.SH",),
            "source_freq": "1min",
            "start_datetime": "2026-08-04 09:30:00",
            "end_datetime": "2026-08-04 15:00:00",
            "request_policy": _policy(),
        }
        arguments.update(kwargs)
        with pytest.raises(MajorIndexMinsFetchError, match=match):
            fetch_major_index_mins_window(**arguments)
