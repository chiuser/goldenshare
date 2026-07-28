from __future__ import annotations

from orchestrator.defs.bootstrap.index_global_bootstrap_plan import build_date_plan
from orchestrator.defs.bootstrap.index_global_bootstrap_source_probe import (
    probe_index_global_source,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_FIELDS,
    INDEX_GLOBAL_NORMAL_PHASES,
)


class _FakeTushare:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("synthetic source failure")
        row = {
            "ts_code": "XIN9",
            "trade_date": params["trade_date"],
            "open": 1.0,
            "close": 1.0,
            "high": 1.0,
            "low": 1.0,
            "pre_close": 1.0,
            "change": 0.0,
            "pct_chg": 0.0,
            "swing": 0.0,
            "vol": None,
            "amount": None,
        }
        return TushareResult(rows=[row], columns=tuple(fields), metadata={})


class _FakeTushareByDate:
    def __init__(self, *, empty_dates: set[str]) -> None:
        self.empty_dates = empty_dates
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        if params["trade_date"] in self.empty_dates:
            return TushareResult(rows=[], columns=(), metadata={})
        return TushareResult(
            rows=[
                {
                    "ts_code": "XIN9",
                    "trade_date": params["trade_date"],
                    "open": 1.0,
                    "close": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "pre_close": 1.0,
                    "change": 0.0,
                    "pct_chg": 0.0,
                    "swing": 0.0,
                    "vol": None,
                    "amount": None,
                }
            ],
            columns=tuple(fields),
            metadata={},
        )


def test_source_probe_requests_each_date_and_phase_without_writing() -> None:
    fake = _FakeTushareByDate(empty_dates={"20220101"})
    report = probe_index_global_source(
        tushare=fake,
        date_plan=build_date_plan(start_date="2022-01-01", end_date="2022-01-02"),
        sleep_fn=lambda _seconds: None,
    )

    assert report.should_stop is False
    assert report.attempted_phase_count == 2 * len(INDEX_GLOBAL_NORMAL_PHASES)
    assert report.successful_phase_count == report.attempted_phase_count
    assert report.empty_phase_count == len(INDEX_GLOBAL_NORMAL_PHASES)
    assert report.source_row_count == len(INDEX_GLOBAL_NORMAL_PHASES)
    assert report.request_count == report.attempted_phase_count
    assert report.throttle_wait_ms > 0
    assert len(fake.calls) == report.attempted_phase_count
    assert all(call[0] == "index_global" for call in fake.calls)
    assert all(call[2] == INDEX_GLOBAL_FIELDS for call in fake.calls)


def test_source_probe_stops_on_first_failure_and_is_fail_closed() -> None:
    fake = _FakeTushare(fail_first=True)
    report = probe_index_global_source(
        tushare=fake,
        date_plan=build_date_plan(start_date="2022-01-01", end_date="2022-01-02"),
        sleep_fn=lambda _seconds: None,
    )

    assert report.should_stop is True
    assert report.stop_reason_codes == ("source_probe_failed",)
    assert report.attempted_phase_count == 1
    assert report.failed_phase_count == 1
    assert len(report.failure_samples) == 1
