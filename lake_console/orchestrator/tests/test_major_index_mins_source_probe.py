from orchestrator.defs.asset_guards.major_index_mins_source_probe import (
    probe_major_index_mins_source,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_DAILY_CODES,
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class _FakeTushare:
    def __init__(self, *, missing_code: str | None = None) -> None:
        self.missing_code = missing_code
        self.calls: list[tuple[str, dict[str, object], tuple[str, ...]]] = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        code = str(params["ts_code"])
        if code == self.missing_code or params["offset"]:
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        exchange = "XSHG" if code.endswith(".SH") else "XSHE"
        row = {
            "ts_code": code,
            "freq": "1min",
            "trade_time": "2026-08-04 15:00:00",
            "open": 1.0,
            "close": 1.1,
            "high": 1.2,
            "low": 0.9,
            "vol": 10.0,
            "amount": 11.0,
            "exchange": exchange,
            "vwap": 1.05,
        }
        return TushareResult(rows=[row], columns=tuple(fields), metadata={})


def _policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0,
        max_retries=0,
        max_requests=20,
        max_elapsed_seconds=30,
    )


def test_probe_requests_only_ten_online_codes_once() -> None:
    tushare = _FakeTushare()
    result = probe_major_index_mins_source(
        tushare=tushare,
        trade_date="2026-08-04",
        request_policy=_policy(),
    )
    assert result.ready is True
    assert result.returned_code_count == 10
    assert result.request_count == 10
    assert len(tushare.calls) == 10
    assert "899050.BJ" not in {call[1]["ts_code"] for call in tushare.calls}
    assert all(call[0] == "idx_mins" for call in tushare.calls)
    assert all(call[2] == MAJOR_INDEX_MINS_SOURCE_COLUMNS for call in tushare.calls)
    assert tuple(call[1]["ts_code"] for call in tushare.calls) == (
        MAJOR_INDEX_MINS_DAILY_CODES
    )


def test_probe_fails_closed_when_one_online_code_is_empty() -> None:
    result = probe_major_index_mins_source(
        tushare=_FakeTushare(missing_code=MAJOR_INDEX_MINS_DAILY_CODES[-1]),
        trade_date="2026-08-04",
        request_policy=_policy(),
    )
    assert result.ready is False
    assert result.reason_code == "source_probe_incomplete"
    assert result.returned_code_count == 9
