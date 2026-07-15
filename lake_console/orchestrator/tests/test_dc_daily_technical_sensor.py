from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.sensors import dc_daily_technical_sensor


class _FakeInstance:
    def __init__(self, registered):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, _name):
        return list(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("Gold technical sensor must not read event history")


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
                root=lambda: Path("/tmp/dc-daily-technical-sensor-test"),
            ),
            duckdb=duckdb,
        ),
    )


def _window_and_gap(registered):
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=("2026-07-14", "2026-07-15"),
        min_trade_date="2024-01-02",
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


def _ready(trade_date):
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
    )


def _missing(trade_date):
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="file_missing",
        missing_check_names=("gold_dc_daily_technical_core_check",),
    )


def _failed(trade_date):
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason="gold_dc_daily_technical_core_check_failed",
        failed_check_names=("gold_dc_daily_technical_core_check",),
    )


def _evaluate(context, silver_batch, gold_batch):
    return dc_daily_technical_sensor.gold_dc_daily_technical_update_job_sensor._raw_fn(context)


def _assert_no_dataset_argument(kwargs, batch):
    assert "dataset" not in kwargs
    return batch


def _patch_scan(monkeypatch, context, silver_batch, gold_batch, registered):
    monkeypatch.setattr(
        dc_daily_technical_sensor,
        "_load_window",
        lambda *args, **kwargs: _window_and_gap(registered),
    )
    monkeypatch.setattr(
        dc_daily_technical_sensor,
        "batch_silver_dc_daily_lake_readiness",
        lambda **kwargs: _assert_no_dataset_argument(kwargs, silver_batch),
    )
    monkeypatch.setattr(
        dc_daily_technical_sensor,
        "batch_gold_dc_daily_technical_lake_readiness",
        lambda **kwargs: gold_batch,
    )


def test_sensor_requests_first_gold_gap_when_silver_is_ready(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    silver = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    gold = _batch({"2026-07-14": _missing("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    _patch_scan(monkeypatch, context, silver, gold, ("2026-07-14", "2026-07-15"))

    result = _evaluate(context, silver, gold)
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == "2026-07-14"
    assert result.run_requests[0].run_key == "gold_dc_daily_technical_update:2026-07-14"
    assert context.resources.duckdb.connection_count == 1
    assert len(result.cursor.encode("ascii")) < 8192


def test_sensor_blocks_when_silver_frontier_does_not_cover_gold(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    silver = _batch({"2026-07-14": _missing("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    gold = _batch({"2026-07-14": _missing("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    _patch_scan(monkeypatch, context, silver, gold, ("2026-07-14", "2026-07-15"))

    result = _evaluate(context, silver, gold)
    assert result.run_requests == []
    assert "silver_not_ready" in result.cursor


def test_sensor_does_not_overwrite_materialized_failed_gold(monkeypatch) -> None:
    context = _context(("2026-07-14", "2026-07-15"))
    silver = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    gold = _batch({"2026-07-14": _failed("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    _patch_scan(monkeypatch, context, silver, gold, ("2026-07-14", "2026-07-15"))

    result = _evaluate(context, silver, gold)
    assert result.run_requests == []
    assert "gold_materialized_check_failed" in result.cursor


def test_sensor_registered_gap_skips_before_readiness(monkeypatch) -> None:
    context = _context(())
    silver = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    gold = _batch({"2026-07-14": _ready("2026-07-14"), "2026-07-15": _ready("2026-07-15")})
    _patch_scan(monkeypatch, context, silver, gold, ())

    def fail_if_called(**_kwargs):
        raise AssertionError("readiness must not run before partition-gap gate")

    monkeypatch.setattr(dc_daily_technical_sensor, "batch_silver_dc_daily_lake_readiness", fail_if_called)
    monkeypatch.setattr(dc_daily_technical_sensor, "batch_gold_dc_daily_technical_lake_readiness", fail_if_called)
    result = _evaluate(context, silver, gold)
    assert result.run_requests == []
    assert "missing_registered_partition" in result.cursor
