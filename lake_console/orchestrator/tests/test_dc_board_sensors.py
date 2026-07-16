from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import DcBoardSourceProbeResult
from orchestrator.defs.sensors import dc_board_sensor


class _FakeInstance:
    def __init__(self, registered):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, _name):
        return list(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("dc board sensors must not read Dagster event history")


class _NoopConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDuckDB:
    def __init__(self):
        self.connection_count = 0

    def connect(self):
        self.connection_count += 1
        return _NoopConnection()


def _context(registered):
    duckdb_resource = _FakeDuckDB()
    resources = SimpleNamespace(
        lake_root=SimpleNamespace(
            ensure_available_for_run=lambda: None,
            root=lambda: Path("/tmp/dc-board-test"),
        ),
        duckdb=duckdb_resource,
        tushare=object(),
    )
    return SimpleNamespace(
        instance=_FakeInstance(registered),
        resources=resources,
        duckdb_resource=duckdb_resource,
    )


def _window_and_gap(registered):
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=("2026-07-14",),
        min_trade_date="2024-01-02",
        max_trade_date="2026-07-14",
        evaluated_at=datetime.now(),
        window_limit=10,
    )
    gap = build_registered_gap_status(
        expected_trade_dates=window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return window, tuple(registered), gap


def _ready_probe(dataset="dc_index"):
    return DcBoardSourceProbeResult(
        dataset=dataset,
        trade_date="2026-07-14",
        ready=True,
        reason_code="ready",
        request_count=1,
        retry_count=0,
        elapsed_ms=1.0,
        successful_count=1,
        empty_count=0,
        failed_count=0,
        unattempted_count=0,
    )


def test_sensor_skips_registered_gap_without_running_readiness(monkeypatch) -> None:
    context = _context(())
    monkeypatch.setattr(
        dc_board_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(()),
    )

    def _unexpected_batch(**_kwargs):
        raise AssertionError("batch readiness must not run before registered-gap gate")

    result = dc_board_sensor._evaluate_sensor(
        context,
        evaluated_at=datetime.now(dc_board_sensor.CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_index_update_job_sensor",
        job_name="raw_tushare_dc_index_update_job",
        dataset="dc_index",
        min_trade_date="2024-01-02",
        batch_reader=_unexpected_batch,
        source_probe_reader=lambda **_kwargs: _ready_probe(),
        partition_set="cn_a_dc_index_trade_days",
    )
    assert not result.run_requests
    assert "missing_registered_partition" in result.cursor


def test_sensor_returns_one_request_for_first_missing_file(monkeypatch) -> None:
    context = _context(("2026-07-14",))
    monkeypatch.setattr(
        dc_board_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(("2026-07-14",)),
    )
    batch = ContinuityBatchReadiness(
        expected_trade_dates=("2026-07-14",),
        statuses_by_trade_date={
            "2026-07-14": ContinuityDateReadiness(
                trade_date="2026-07-14",
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="dc_index file is missing",
                missing_check_names=("raw_tushare_dc_index_core_check",),
            )
        },
        elapsed_ms=3,
        scanned_file_count=0,
    )
    calls = []

    def _batch(**_kwargs):
        calls.append(True)
        return batch

    result = dc_board_sensor._evaluate_sensor(
        context,
        evaluated_at=datetime.now(dc_board_sensor.CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_index_update_job_sensor",
        job_name="raw_tushare_dc_index_update_job",
        dataset="dc_index",
        min_trade_date="2024-01-02",
        batch_reader=_batch,
        source_probe_reader=lambda **_kwargs: _ready_probe(),
        partition_set="cn_a_dc_index_trade_days",
    )
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == "2026-07-14"
    assert result.run_requests[0].run_key == "raw_tushare_dc_index_update:2026-07-14"
    assert calls == [True]
    assert context.duckdb_resource.connection_count == 1
