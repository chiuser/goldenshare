from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import raw_major_index_mins_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_AUTO_RETRY_LIMIT,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
)
from orchestrator.defs.sensors import (
    major_index_mins_partition_sensor,
    major_index_mins_sensor,
)

TRADE_DATE = "2026-08-04"


class _NoEventHistoryInstance:
    def __init__(self, *, run_records: tuple[object, ...] = ()) -> None:
        self.event_history_calls = 0
        self.run_record_calls = 0
        self.run_records = run_records
        self.last_run_filter = None
        self.last_run_limit = None

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == cn_major_index_mins_trade_days.name
        return [TRADE_DATE]

    def get_event_records(self, *args, **kwargs):
        self.event_history_calls += 1
        raise AssertionError("major_index_mins sensors must not read event history")

    def get_run_records(self, *, filters, limit):
        self.run_record_calls += 1
        self.last_run_filter = filters
        self.last_run_limit = limit
        return list(self.run_records[:limit])


class _CountingDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield object()


def _context(*, run_records: tuple[object, ...] = ()) -> SimpleNamespace:
    root = Path(TemporaryDirectory().name)
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        resources=SimpleNamespace(
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb=_CountingDuckDB(),
            tushare=object(),
        ),
        instance=_NoEventHistoryInstance(run_records=run_records),
    )


def _window_and_gap():
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=(TRADE_DATE,),
        min_trade_date="2009-01-05",
        max_trade_date=TRADE_DATE,
        evaluated_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        window_limit=10,
    )
    registered = (TRADE_DATE,)
    return (
        window,
        registered,
        build_registered_gap_status(
            expected_trade_dates=window.expected_trade_dates,
            registered_trade_dates=registered,
        ),
    )


def _batch(*, materialized: bool, checks_passed: bool) -> ContinuityBatchReadiness:
    status = ContinuityDateReadiness(
        trade_date=TRADE_DATE,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "missing",
    )
    return ContinuityBatchReadiness(
        expected_trade_dates=(TRADE_DATE,),
        statuses_by_trade_date={TRADE_DATE: status},
        elapsed_ms=1,
        scanned_file_count=5,
    )


def _probe(*, ready: bool = True, source_freq: str = "1min") -> SimpleNamespace:
    return SimpleNamespace(
        source_freq=source_freq,
        ready=ready,
        reason_code="ready" if ready else "source_probe_incomplete",
        expected_code_count=10,
        returned_code_count=10 if ready else 9,
        request_count=10,
        retry_count=0,
        elapsed_ms=1.0,
    )


def _run_record(run_key: str, status: dg.DagsterRunStatus) -> SimpleNamespace:
    return SimpleNamespace(
        dagster_run=SimpleNamespace(
            tags={
                "dagster/run_key": run_key,
                "dagster/partition": TRADE_DATE,
            },
            status=status,
        )
    )


def _create_existing_raw_frequencies(
    context: SimpleNamespace,
    *,
    missing_freqs: tuple[str, ...],
) -> None:
    root = context.resources.lake_root.root()
    for source_freq in MAJOR_INDEX_MINS_SOURCE_FREQS:
        if source_freq in missing_freqs:
            continue
        path = raw_major_index_mins_path(root, source_freq, TRADE_DATE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def test_raw_sensor_requests_one_run_after_bounded_probe() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
            return_value=_probe(),
        ),
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == (
        f"raw_major_index_mins_update:{TRADE_DATE}"
    )
    assert context.resources.duckdb.connection_count == 1
    assert context.instance.event_history_calls == 0
    assert context.instance.run_record_calls == 1
    assert context.instance.last_run_limit == MAJOR_INDEX_MINS_RAW_AUTO_RETRY_LIMIT + 1
    assert context.instance.last_run_filter.job_name == "raw_major_index_mins_update_job"
    assert context.instance.last_run_filter.tags == {
        "dagster/partition": TRADE_DATE,
    }
    assert len(result.cursor.encode("utf-8")) < 8192
    assert json.loads(result.cursor)["details"]["reason_code"] == "request_run"


def test_raw_sensor_does_not_probe_materialized_failure() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=True, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)
    assert result.run_requests == []
    assert probe.call_count == 0
    assert context.instance.run_record_calls == 0


def test_raw_sensor_retries_one_missing_frequency_with_attempt_key() -> None:
    initial_key = f"raw_major_index_mins_update:{TRADE_DATE}"
    context = _context(
        run_records=(_run_record(initial_key, dg.DagsterRunStatus.FAILURE),)
    )
    _create_existing_raw_frequencies(context, missing_freqs=("5min",))
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
            return_value=_probe(source_freq="5min"),
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_key == (
        f"raw_major_index_mins_update:{TRADE_DATE}:retry:1"
    )
    assert probe.call_args.kwargs["source_freq"] == "5min"
    cursor = json.loads(result.cursor)
    assert cursor["details"]["reason_code"] == "request_retry_run"
    assert cursor["details"]["summary"] == "5min 源数据已齐，提交 Raw 第 1 次自动重试"
    assert cursor["details"]["evidence"]["run_attempt"] == 1
    assert cursor["details"]["evidence"]["missing_source_freq"] == "5min"


def test_raw_sensor_rejects_retry_when_multiple_frequencies_are_missing() -> None:
    initial_key = f"raw_major_index_mins_update:{TRADE_DATE}"
    context = _context(
        run_records=(_run_record(initial_key, dg.DagsterRunStatus.FAILURE),)
    )
    _create_existing_raw_frequencies(
        context,
        missing_freqs=("5min", "15min"),
    )
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "raw_retry_scope_not_single_frequency"
    )


def test_raw_sensor_stops_after_retry_attempt_budget_is_exhausted() -> None:
    run_keys = major_index_mins_sensor._raw_run_candidate_keys(TRADE_DATE)
    context = _context(
        run_records=tuple(
            _run_record(run_key, dg.DagsterRunStatus.FAILURE)
            for run_key in run_keys
        )
    )
    _create_existing_raw_frequencies(context, missing_freqs=("5min",))
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "raw_retry_exhausted"
    )


def test_raw_sensor_waits_for_active_attempt_without_source_probe() -> None:
    initial_key = f"raw_major_index_mins_update:{TRADE_DATE}"
    context = _context(
        run_records=(_run_record(initial_key, dg.DagsterRunStatus.STARTED),)
    )
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == "raw_run_active"


def test_raw_sensor_rejects_noncanonical_partition_run_identity() -> None:
    context = _context(
        run_records=(
            _run_record("manually-launched-without-canonical-key", dg.DagsterRunStatus.STARTED),
        )
    )
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "raw_retry_identity_conflict"
    )


def test_raw_sensor_rejects_successful_run_when_target_file_is_missing() -> None:
    initial_key = f"raw_major_index_mins_update:{TRADE_DATE}"
    context = _context(
        run_records=(_run_record(initial_key, dg.DagsterRunStatus.SUCCESS),)
    )
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
        patch.object(
            major_index_mins_sensor,
            "probe_major_index_mins_source",
        ) as probe,
    ):
        result = major_index_mins_sensor._evaluate_raw_sensor(context)

    assert result.run_requests == []
    assert probe.call_count == 0
    assert json.loads(result.cursor)["details"]["reason_code"] == (
        "raw_run_success_without_files"
    )


def test_silver_sensor_waits_for_raw_then_requests_one_run() -> None:
    context = _context()
    window, registered, gap = _window_and_gap()
    with (
        patch.object(
            major_index_mins_sensor,
            "_load_window",
            return_value=(window, registered, gap),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_raw_major_index_mins_lake_readiness",
            return_value=_batch(materialized=True, checks_passed=True),
        ),
        patch.object(
            major_index_mins_sensor,
            "batch_silver_major_index_mins_lake_readiness",
            return_value=_batch(materialized=False, checks_passed=False),
        ),
    ):
        result = major_index_mins_sensor._evaluate_silver_sensor(context)
    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_key == (
        f"silver_major_index_mins_update:{TRADE_DATE}"
    )
    assert context.resources.duckdb.connection_count == 1
    assert context.instance.event_history_calls == 0


def test_sensor_definitions_default_to_stopped() -> None:
    assert (
        major_index_mins_sensor.raw_major_index_mins_update_job_sensor.default_status.value
        == "STOPPED"
    )
    assert (
        major_index_mins_sensor.silver_major_index_mins_update_job_sensor.default_status.value
        == "STOPPED"
    )
    assert (
        major_index_mins_partition_sensor.major_index_mins_trade_day_sensor.default_status.value
        == "STOPPED"
    )
