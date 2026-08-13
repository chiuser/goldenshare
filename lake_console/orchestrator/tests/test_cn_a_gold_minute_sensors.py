from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.sensors import cn_a_gold_minute_sensor
from orchestrator.defs.sensors.cn_a_gold_minute_sensor import (
    CanonicalGoldMinuteSensorSpec,
    evaluate_canonical_gold_minute_sensor,
)

TRADE_DATE = "2026-08-12"


class _NoEventHistoryInstance:
    def __init__(self, registered: tuple[str, ...]) -> None:
        self._registered = registered
        self.event_history_calls = 0

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self._registered)

    def get_event_records(self, *_args, **_kwargs):
        self.event_history_calls += 1
        raise AssertionError("Gold minute sensors must not read event history")


class _CountingDuckDB:
    def __init__(self) -> None:
        self.connection_count = 0

    @contextmanager
    def connect(self):
        self.connection_count += 1
        yield object()


def _context(registered: tuple[str, ...]):
    duckdb = _CountingDuckDB()
    instance = _NoEventHistoryInstance(registered)
    return SimpleNamespace(
        instance=instance,
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/private/tmp/cn-a-gold-minute-sensor-test"),
            ),
            duckdb=duckdb,
        ),
        duckdb_resource=duckdb,
    )


def _status(*, materialized: bool, checks_passed: bool):
    return ContinuityDateReadiness(
        trade_date=TRADE_DATE,
        ready=materialized and checks_passed,
        materialized=materialized,
        checks_passed=checks_passed,
        reason="ready" if materialized and checks_passed else "not_ready",
        missing_check_names=("core_check",) if not materialized else (),
        failed_check_names=("core_check",)
        if materialized and not checks_passed
        else (),
        summary={
            "reason_code": (
                "ready"
                if materialized and checks_passed
                else "core_check_failed"
                if materialized
                else "file_missing"
            )
        },
    )


def _batch(*, materialized: bool, checks_passed: bool):
    return ContinuityBatchReadiness(
        expected_trade_dates=(TRADE_DATE,),
        statuses_by_trade_date={
            TRADE_DATE: _status(
                materialized=materialized,
                checks_passed=checks_passed,
            )
        },
        elapsed_ms=2,
        scanned_file_count=7 if materialized else 0,
    )


def _spec(source_batch, gold_batch, calls: list[str]):
    def source_loader(**_kwargs):
        calls.append("source")
        return source_batch

    def gold_loader(**_kwargs):
        calls.append("gold")
        return gold_batch

    return CanonicalGoldMinuteSensorSpec(
        sensor_name="gold_test_mins_update_job_sensor",
        job_name="gold_test_mins_update_job",
        asset_family="test_mins",
        min_trade_date="2025-01-02",
        partition_set_name="cn_test_mins_trade_days",
        silver_readiness_loader=source_loader,
        gold_readiness_loader=gold_loader,
    )


def _patch_window(monkeypatch) -> None:
    monkeypatch.setattr(
        cn_a_gold_minute_sensor,
        "load_expected_trade_date_window",
        lambda *_args, **_kwargs: ContinuityExpectedDateWindow(
            expected_trade_dates=(TRADE_DATE,),
            min_trade_date="2025-01-02",
            max_trade_date=TRADE_DATE,
            evaluated_at=datetime(
                2026,
                8,
                13,
                20,
                0,
                tzinfo=cn_a_gold_minute_sensor.CN_A_SENSOR_TIMEZONE,
            ),
            window_limit=10,
        ),
    )


def test_sensor_requests_one_gold_run_when_silver_is_ready(monkeypatch) -> None:
    _patch_window(monkeypatch)
    context = _context((TRADE_DATE,))
    calls: list[str] = []
    result = evaluate_canonical_gold_minute_sensor(
        context,
        spec=_spec(
            _batch(materialized=True, checks_passed=True),
            _batch(materialized=False, checks_passed=False),
            calls,
        ),
    )

    assert calls == ["source", "gold"]
    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert result.run_requests[0].run_key == f"gold_test_mins_update:{TRADE_DATE}"
    assert context.duckdb_resource.connection_count == 1
    assert context.instance.event_history_calls == 0
    assert len(result.cursor.encode("ascii")) < 8192


def test_sensor_waits_when_same_day_silver_is_not_ready(monkeypatch) -> None:
    _patch_window(monkeypatch)
    context = _context((TRADE_DATE,))
    result = evaluate_canonical_gold_minute_sensor(
        context,
        spec=_spec(
            _batch(materialized=False, checks_passed=False),
            _batch(materialized=False, checks_passed=False),
            [],
        ),
    )

    assert result.run_requests == []
    assert "silver_not_ready" in result.cursor


def test_sensor_does_not_overwrite_materialized_failed_gold(monkeypatch) -> None:
    _patch_window(monkeypatch)
    context = _context((TRADE_DATE,))
    result = evaluate_canonical_gold_minute_sensor(
        context,
        spec=_spec(
            _batch(materialized=True, checks_passed=True),
            _batch(materialized=True, checks_passed=False),
            [],
        ),
    )

    assert result.run_requests == []
    assert "materialized_check_failed" in result.cursor


def test_sensor_stops_before_readiness_when_partition_is_unregistered(
    monkeypatch,
) -> None:
    _patch_window(monkeypatch)
    context = _context(())
    calls: list[str] = []
    result = evaluate_canonical_gold_minute_sensor(
        context,
        spec=_spec(
            _batch(materialized=True, checks_passed=True),
            _batch(materialized=False, checks_passed=False),
            calls,
        ),
    )

    assert result.run_requests == []
    assert calls == []
    assert "missing_registered_partition" in result.cursor


def test_sensor_skips_when_gold_window_is_ready(monkeypatch) -> None:
    _patch_window(monkeypatch)
    context = _context((TRADE_DATE,))
    result = evaluate_canonical_gold_minute_sensor(
        context,
        spec=_spec(
            _batch(materialized=True, checks_passed=True),
            _batch(materialized=True, checks_passed=True),
            [],
        ),
    )

    assert result.run_requests == []
    assert "all_ready" in result.cursor
