from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.sensors.prod_dc_daily_technical_sensor import (
    prod_ch_dc_daily_technical_continuity_sensor,
)


DATE = "2026-07-14"


class _FakeInstance:
    def get_dynamic_partitions(self, _name):
        return [DATE]

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("Prod technical sensor must not read event history")


class _FakeConnectionResource:
    @contextmanager
    def get_connection(self):
        yield object()


class _FakeDuckDB:
    @contextmanager
    def connect(self):
        yield object()


class _FakeContext:
    def __init__(self):
        self.instance = _FakeInstance()
        self.resources = SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/tmp/dc-daily-technical-test"),
            ),
            duckdb=_FakeDuckDB(),
            clickhouse=_FakeConnectionResource(),
            prod_clickhouse=_FakeConnectionResource(),
        )


def _window() -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=(DATE,),
        min_trade_date="2024-01-02",
        max_trade_date=DATE,
        evaluated_at=datetime(2026, 7, 14, 21, 0),
        window_limit=10,
    )


def _batch(local_ready: bool, prod_ready: bool) -> ContinuityBatchReadiness:
    local_status = {
        "ready": local_ready,
        "materialized": local_ready,
        "checks_passed": local_ready,
        "reason": "ready" if local_ready else "missing_clickhouse_partition",
    }
    prod_status = {
        "ready": prod_ready,
        "materialized": prod_ready,
        "checks_passed": prod_ready,
        "reason": "ready" if prod_ready else "missing_clickhouse_partition",
    }
    status = ContinuityDateReadiness(
        trade_date=DATE,
        ready=local_ready and prod_ready,
        materialized=local_ready and prod_ready,
        checks_passed=local_ready and prod_ready,
        reason="ready" if local_ready and prod_ready else "missing_prod_clickhouse_partition",
        summary={
            "local": {**local_status},
            "prod": {**prod_status},
        },
    )
    return ContinuityBatchReadiness(
        expected_trade_dates=(DATE,),
        statuses_by_trade_date={DATE: status},
        elapsed_ms=3,
    )


def _run_sensor(batch):
    context = _FakeContext()
    window = _window()
    gap = build_registered_gap_status(
        expected_trade_dates=(DATE,),
        registered_trade_dates=(DATE,),
    )
    with (
        patch(
            "orchestrator.defs.sensors.prod_dc_daily_technical_sensor.load_expected_trade_date_window",
            return_value=window,
        ),
        patch(
            "orchestrator.defs.sensors.prod_dc_daily_technical_sensor.batch_prod_ch_dc_daily_technical_lake_readiness",
            return_value=batch,
        ),
    ):
        return prod_ch_dc_daily_technical_continuity_sensor._raw_fn(context)


def test_prod_sensor_waits_for_local_serving() -> None:
    result = _run_sensor(_batch(local_ready=False, prod_ready=False))
    assert result.run_requests == []
    assert result.skip_reason.skip_message == "local_not_ready"


def test_prod_sensor_submits_only_when_local_ready_and_prod_missing() -> None:
    result = _run_sensor(_batch(local_ready=True, prod_ready=False))
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == DATE
    assert result.run_requests[0].run_key == (
        "prod_ch_dc_daily_technical_sync:2026-07-14"
    )


def test_prod_sensor_skips_when_both_are_ready() -> None:
    result = _run_sensor(_batch(local_ready=True, prod_ready=True))
    assert result.run_requests == []
    assert result.skip_reason.skip_message == "all_ready"
