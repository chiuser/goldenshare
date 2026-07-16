from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.sensors import dc_board_silver_sensor


class _FakeInstance:
    def __init__(self, registered):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, _name):
        return list(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("Silver board sensors must not read Dagster event history")


class _FakeDuckDB:
    def __init__(self):
        self.connection_count = 0

    def connect(self):
        self.connection_count += 1

        class _Context:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Context()


def _context(registered):
    duckdb = _FakeDuckDB()
    return SimpleNamespace(
        instance=_FakeInstance(registered),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/tmp/dc-board-silver-test"),
            ),
            duckdb=duckdb,
        ),
        duckdb_resource=duckdb,
    )


def _window_and_gap(registered):
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=("2026-07-14", "2026-07-15"),
        min_trade_date="2024-12-20",
        max_trade_date="2026-07-15",
        evaluated_at=datetime.now(),
        window_limit=10,
    )
    return (
        window,
        tuple(registered),
        build_registered_gap_status(
            expected_trade_dates=window.expected_trade_dates,
            registered_trade_dates=registered,
        ),
    )


def _batch(statuses):
    return ContinuityBatchReadiness(
        expected_trade_dates=tuple(statuses),
        statuses_by_trade_date=statuses,
        elapsed_ms=3,
        scanned_file_count=sum(status.materialized for status in statuses.values()),
    )


def _ready(date):
    return ContinuityDateReadiness(
        trade_date=date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
    )


def _missing(date, check_name):
    return ContinuityDateReadiness(
        trade_date=date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="file is missing",
        missing_check_names=(check_name,),
    )


def _failed(date, check_name):
    return ContinuityDateReadiness(
        trade_date=date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason="core checks failed",
        failed_check_names=(check_name,),
    )


def _evaluate(context, raw_batch, silver_batch):
    return dc_board_silver_sensor._evaluate_silver_sensor(
        context,
        evaluated_at=datetime.now(dc_board_silver_sensor.CN_A_SENSOR_TIMEZONE),
        sensor_name="silver_dc_index_update_job_sensor",
        job_name="silver_dc_index_update_job",
        min_trade_date="2024-12-20",
        raw_reader=lambda **_kwargs: raw_batch,
        silver_reader=lambda **_kwargs: silver_batch,
        partition_set="cn_a_dc_index_trade_days",
    )


def test_silver_sensor_requests_first_gap_when_raw_frontier_covers_it(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    monkeypatch.setattr(
        dc_board_silver_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(("2026-07-14", "2026-07-15")),
    )
    raw = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    silver = _batch(
        {
            "2026-07-14": _missing("2026-07-14", "silver_dc_index_core_check"),
            "2026-07-15": _ready("2026-07-15"),
        }
    )
    result = _evaluate(context, raw, silver)
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == "2026-07-14"
    assert result.run_requests[0].run_key == "silver_dc_index_update:2026-07-14"
    assert context.duckdb_resource.connection_count == 1
    assert len(result.cursor.encode("ascii")) < 8192


def test_silver_sensor_blocks_when_raw_is_not_ready_at_target(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    monkeypatch.setattr(
        dc_board_silver_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(("2026-07-14", "2026-07-15")),
    )
    raw = _batch(
        {
            "2026-07-14": _missing("2026-07-14", "raw_tushare_dc_index_core_check"),
            "2026-07-15": _ready("2026-07-15"),
        }
    )
    silver = _batch(
        {
            "2026-07-14": _missing("2026-07-14", "silver_dc_index_core_check"),
            "2026-07-15": _ready("2026-07-15"),
        }
    )
    result = _evaluate(context, raw, silver)
    assert not result.run_requests
    assert "raw_not_ready" in result.cursor


def test_silver_sensor_can_process_earlier_gap_when_raw_issue_is_later(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    monkeypatch.setattr(
        dc_board_silver_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(("2026-07-14", "2026-07-15")),
    )
    raw = _batch(
        {
            "2026-07-14": _ready("2026-07-14"),
            "2026-07-15": _missing("2026-07-15", "raw_tushare_dc_index_core_check"),
        }
    )
    silver = _batch(
        {
            "2026-07-14": _missing("2026-07-14", "silver_dc_index_core_check"),
            "2026-07-15": _ready("2026-07-15"),
        }
    )
    result = _evaluate(context, raw, silver)
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == "2026-07-14"


def test_silver_sensor_does_not_overwrite_materialized_failed_partition(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    monkeypatch.setattr(
        dc_board_silver_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(("2026-07-14", "2026-07-15")),
    )
    raw = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    silver = _batch(
        {
            "2026-07-14": _failed("2026-07-14", "silver_dc_index_core_check"),
            "2026-07-15": _ready("2026-07-15"),
        }
    )
    result = _evaluate(context, raw, silver)
    assert not result.run_requests
    assert "silver_materialized_check_failed" in result.cursor


def test_silver_sensor_skips_registered_gap_without_batch_scan(monkeypatch) -> None:
    context = _context(())
    monkeypatch.setattr(
        dc_board_silver_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(()),
    )
    calls = []

    def _unexpected(**_kwargs):
        calls.append(True)
        raise AssertionError("readiness must not run before registered-gap gate")

    result = dc_board_silver_sensor._evaluate_silver_sensor(
        context,
        evaluated_at=datetime.now(dc_board_silver_sensor.CN_A_SENSOR_TIMEZONE),
        sensor_name="silver_dc_index_update_job_sensor",
        job_name="silver_dc_index_update_job",
        min_trade_date="2024-12-20",
        raw_reader=_unexpected,
        silver_reader=_unexpected,
        partition_set="cn_a_dc_index_trade_days",
    )
    assert not result.run_requests
    assert calls == []
