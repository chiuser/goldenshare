from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.sensors import index_mins_partition_sensor, index_mins_sensor


TRADE_DATE = "2026-07-27"


class _NoEventHistoryInstance:
    def __init__(self) -> None:
        self.event_history_calls = 0

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == cn_a_index_mins_trade_days.name
        return [TRADE_DATE]

    def get_event_records(self, *args, **kwargs):
        self.event_history_calls += 1
        raise AssertionError("index_mins sensors must not read Dagster event history")


class _CountingDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield object()


def _context() -> SimpleNamespace:
    root = Path(TemporaryDirectory().name)
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        resources=SimpleNamespace(
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb=_CountingDuckDB(),
            prod_postgres=object(),
        ),
        instance=_NoEventHistoryInstance(),
    )


def _window_and_gap() -> tuple[ContinuityExpectedDateWindow, tuple[str, ...], object]:
    evaluated_at = datetime(2026, 7, 28, 20, 0)
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=(TRADE_DATE,),
        min_trade_date="2025-01-02",
        max_trade_date=TRADE_DATE,
        evaluated_at=evaluated_at,
        window_limit=10,
    )
    registered = (TRADE_DATE,)
    return window, registered, build_registered_gap_status(
        expected_trade_dates=window.expected_trade_dates,
        registered_trade_dates=registered,
    )


def _batch(*, materialized: bool, checks_passed: bool) -> ContinuityBatchReadiness:
    status = ContinuityDateReadiness(
        trade_date=TRADE_DATE,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "missing",
        missing_check_names=("core_check",) if not materialized else (),
    )
    return ContinuityBatchReadiness(
        expected_trade_dates=(TRADE_DATE,),
        statuses_by_trade_date={TRADE_DATE: status},
        elapsed_ms=1,
        scanned_file_count=5,
    )


def _source_ready() -> SimpleNamespace:
    coverage = tuple(
        SimpleNamespace(
            source_row_count=1,
            returned_code_count=1,
            expected_code_count=1,
            duplicate_key_count=0,
        )
        for _ in range(5)
    )
    return SimpleNamespace(
        ready=True,
        reason_code="ready",
        expected_code_count=1,
        expected_code_set_hash="hash",
        frequency_coverages=coverage,
        elapsed_ms=1,
    )


def _active_pool() -> SimpleNamespace:
    return SimpleNamespace(codes=("000001.SH",), code_count=1, code_set_hash="hash")


def test_raw_sensor_requests_one_run_after_source_probe_and_uses_one_connection() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    with (
        patch.object(index_mins_sensor, "_load_window", return_value=(window, registered, gap)),
        patch.object(index_mins_sensor, "batch_raw_index_mins_lake_readiness", return_value=_batch(materialized=False, checks_passed=False)),
        patch.object(index_mins_sensor, "load_prod_index_mins_active_pool", return_value=_active_pool()),
        patch.object(index_mins_sensor, "probe_prod_index_mins_source", return_value=_source_ready()),
    ):
        result = index_mins_sensor._evaluate_raw_sensor(context)

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == f"raw_index_mins_update:{TRADE_DATE}"
    assert context.resources.duckdb.connection_count == 1
    assert context.instance.event_history_calls == 0
    assert len(result.cursor.encode("utf-8")) < 8192
    assert json.loads(result.cursor)["details"]["reason_code"] == "request_run"


def test_raw_sensor_stops_on_materialized_failure_without_source_probe() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    with (
        patch.object(index_mins_sensor, "_load_window", return_value=(window, registered, gap)),
        patch.object(index_mins_sensor, "batch_raw_index_mins_lake_readiness", return_value=_batch(materialized=True, checks_passed=False)),
        patch.object(index_mins_sensor, "load_prod_index_mins_active_pool") as load_pool,
    ):
        result = index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert load_pool.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == "materialized_check_failed"


def test_silver_sensor_waits_for_raw_frontier_and_then_requests_one_run() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    raw_ready = _batch(materialized=True, checks_passed=True)
    silver_missing = _batch(materialized=False, checks_passed=False)
    with (
        patch.object(index_mins_sensor, "_load_window", return_value=(window, registered, gap)),
        patch.object(index_mins_sensor, "batch_raw_index_mins_lake_readiness", return_value=raw_ready),
        patch.object(index_mins_sensor, "batch_silver_index_mins_lake_readiness", return_value=silver_missing),
    ):
        result = index_mins_sensor._evaluate_silver_sensor(context)

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == f"silver_index_mins_update:{TRADE_DATE}"
    assert context.resources.duckdb.connection_count == 1
    assert context.instance.event_history_calls == 0


def test_sensor_definitions_and_partition_registration_are_stopped() -> None:
    assert index_mins_sensor.raw_index_mins_update_job_sensor.default_status.value == "STOPPED"
    assert index_mins_sensor.silver_index_mins_update_job_sensor.default_status.value == "STOPPED"
    assert index_mins_partition_sensor.index_mins_trade_day_sensor.default_status.value == "STOPPED"
