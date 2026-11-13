"""Stage-1 owned processes and real HTTP; artificial 5218-code fixture only."""

import json
import logging
import time
from types import SimpleNamespace

import pytest

from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.defs.source_readiness import moneyflow_daily
from orchestrator.defs.source_readiness import moneyflow_transport as parent
from tests.test_moneyflow_ths_http_worker import (
    DATA,
    FIELDS,
    PROJECTION,
    TOKEN,
    Reply,
    call_ths,
    local_sdk_server,
    localhost_source,
    source_body,
)

pytest_plugins = ("tests.test_moneyflow_ths_http_worker",)


def artificial_page(offset):
    """Fixture expansion only; expected results below use independent literals."""
    return [
        {"trade_date": "20261110", "ts_code": f"{i:06d}.SZ", **(
            {name: None for name in FIELDS[2:]}
            if i == 1 else DATA["default_business_values"]
        )}
        for i in range(offset + 1, min(offset + 2000, 5218) + 1)
    ]


def assert_page(rows, offset, *, projection=False):
    assert len(rows) == (1218 if offset == 4000 else 2000)
    for i, row in enumerate(rows, offset + 1):
        assert row["ts_code"] == f"{i:06d}.SZ"
        assert row["trade_date"] == "20261110"
        if projection:
            assert tuple(row) == ("ts_code", "trade_date")
        elif i == 1:
            assert tuple(row) == FIELDS
            assert all(row[name] is None for name in FIELDS[2:])
        else:
            # Literal gold result, not the fixture expander or production parser.
            assert tuple(row.values()) == (
                "20261110", f"{i:06d}.SZ", "人工样本", "-1.2345", "10.2301",
                "-1234.5678", "9007199254740993.0001", 0, 0, "12.3456",
                "1.2501", "-12.3456", "-1.2501",
            )


def record_page_cost(probe, timing_path, finished, caplog):
    _, started = probe.owned[-1]
    times = json.loads(timing_path.read_text())
    t1, t2, t3 = (times[k] for k in ("t1", "t2", "t3"))
    assert started <= t1 <= t2 <= t3 <= finished
    metric = next(r.args for r in reversed(caplog.records) if r.name == parent.__name__)
    assert 0 < metric[2] < metric[3] <= 768 * 1024 * 1024
    return {
        "launch_seconds": t1 - started,
        "initialization_seconds": t2 - t1,
        "http_seconds": t3 - t2,
        "result_and_cleanup_seconds": finished - t3,
        "wall_seconds": finished - started,
        "child_peak_rss_bytes": metric[2], "pair_peak_upper_bytes": metric[3],
    }


def test_ths_full_fields_rounds_and_cost(ths_probe, tmp_path, monkeypatch, caplog, record_property):
    costs, completed, consumed = [], [], []
    real_call = parent.call_moneyflow_source

    def measured(*args, **kwargs):
        timing_path = tmp_path / f"full-{len(costs)}.json"
        result = real_call(*args, **kwargs, _command=lambda d: ths_probe.command(d, timing_path))
        costs.append(record_page_cost(ths_probe, timing_path, time.perf_counter(), caplog))
        return result

    def consume(round_number, content_type, offset, rows):
        assert content_type is None
        assert_page(rows, offset)
        consumed.append((round_number, offset, len(rows)))

    def source(payload, _):
        assert payload["fields"] == ",".join(FIELDS)
        assert payload["token"] == TOKEN
        assert payload["params"]["trade_date"] == "20261110"
        assert payload["params"]["limit"] == 2000
        return Reply(200, source_body(FIELDS, artificial_page(payload["params"]["offset"])))

    monkeypatch.setattr(moneyflow_daily, "call_moneyflow_source", measured)
    with localhost_source(source) as (url, received):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        with caplog.at_level(logging.INFO, logger=parent.__name__):
            started = time.perf_counter()
            result = moneyflow_daily.collect_daily_moneyflow(
                tushare=SimpleNamespace(token=TOKEN), dataset="moneyflow_ths",
                trade_date="2026-11-10", consume_page=consume,
                complete_round=lambda n, count: completed.append((n, count)),
            )
            elapsed = time.perf_counter() - started
    assert completed == [(1, 5218), (2, 5218)]
    assert consumed == [(n, offset, size) for n in (1, 2) for offset, size in ((0, 2000), (2000, 2000), (4000, 1218))]
    assert result.row_count == 5218 and result.request_count == 6 and result.retry_count == 0
    assert result.scope_row_counts == (5218,)
    assert result.stability_gap_seconds >= 60 and 60 <= elapsed < 300
    assert len(received) == len(ths_probe.owned) == len(costs) == 6
    record_property("ths_full_fields_cost", json.dumps({
        "loopback_only": True, "unit_seconds": elapsed, "stability_seconds": result.stability_gap_seconds,
        "requests": 6, "rounds": 2, "rows_per_round": 5218, "pages": costs,
    }))


def test_ths_projection_shared_deadline(ths_probe, tmp_path, caplog, record_property):
    costs, row_count = [], 0
    with localhost_source(lambda p, _: Reply(200, source_body(PROJECTION, artificial_page(p["params"]["offset"])))) as (url, received):
        started = time.perf_counter()
        deadline = started + 30  # Existing readiness window, shared by all three pages.
        with caplog.at_level(logging.INFO, logger=parent.__name__):
            for offset in (0, 2000, 4000):
                path = tmp_path / f"keys-{offset}.json"
                result = call_ths(url, fields=PROJECTION, offset=offset, deadline=deadline, command=lambda d, path=path: ths_probe.command(d, path))
                costs.append(record_page_cost(ths_probe, path, time.perf_counter(), caplog))
                assert result.columns == PROJECTION
                assert_page(result.rows, offset, projection=True)
                row_count += len(result.rows)
        elapsed = time.perf_counter() - started
    assert row_count == 5218 and len(received) == len(costs) == len(ths_probe.owned) == 3
    assert elapsed < 30
    assert [r[1]["params"]["offset"] for r in received] == [0, 2000, 4000]
    assert all(r[1]["fields"] == "ts_code,trade_date" for r in received)
    record_property("ths_projection_cost", json.dumps({
        "loopback_only": True, "window_seconds": elapsed, "requests": 3, "rows": row_count, "pages": costs,
    }))


def test_projection_partial_timeout_never_returns_a_complete_day(ths_probe):
    # Eight-second adverse test window includes the existing two-second cleanup.
    deadline = time.perf_counter() + 8
    with localhost_source(lambda *_: Reply(200, source_body(PROJECTION, artificial_page(0)))) as (url, received):
        first = call_ths(url, fields=PROJECTION, deadline=deadline, command=ths_probe.command)
        assert_page(first.rows, 0, projection=True)
        assert len(received) == 1
    with local_sdk_server(slow=True) as (url, received, disconnected):
        with pytest.raises(MoneyflowContractError, match="source_total_deadline|source_worker_failed"):
            call_ths(url, fields=PROJECTION, offset=2000, deadline=deadline, command=ths_probe.command)
        assert len(received) == 1 and disconnected.wait(1)
    assert time.perf_counter() < deadline
    assert len(ths_probe.owned) == 2  # No third page or successful complete result.
