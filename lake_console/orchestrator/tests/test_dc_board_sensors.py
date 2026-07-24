import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardProdReferenceResult,
    DcBoardTushareReferenceComparison,
)
from orchestrator.defs.run_contracts.dc_board import build_dc_board_prod_reference_snapshot
from orchestrator.defs.sensors import dc_board_sensor


_TRADE_DATE = "2026-07-14"


class _FakeInstance:
    def __init__(self, registered):
        self.registered = tuple(registered)

    def get_dynamic_partitions(self, _name):
        return list(self.registered)

    def get_event_records(self, *_args, **_kwargs):
        raise AssertionError("DC board sensor must not read Dagster event history")


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


def _context(registered=(_TRADE_DATE,), *, cursor=None):
    duckdb = _FakeDuckDB()
    return SimpleNamespace(
        cursor=cursor,
        instance=_FakeInstance(registered),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/tmp/dc-board-test"),
            ),
            duckdb=duckdb,
            tushare=object(),
            prod_postgres=object(),
        ),
    )


def _window_and_gap(registered=(_TRADE_DATE,)):
    window = ContinuityExpectedDateWindow(
        expected_trade_dates=(_TRADE_DATE,),
        min_trade_date="2024-01-02",
        max_trade_date=_TRADE_DATE,
        evaluated_at=dc_board_sensor.datetime.now(dc_board_sensor.CN_A_SENSOR_TIMEZONE),
        window_limit=10,
    )
    return window, tuple(registered), build_registered_gap_status(
        expected_trade_dates=window.expected_trade_dates,
        registered_trade_dates=registered,
    )


def _not_ready_batch():
    return ContinuityBatchReadiness(
        expected_trade_dates=(_TRADE_DATE,),
        statuses_by_trade_date={
            _TRADE_DATE: ContinuityDateReadiness(
                trade_date=_TRADE_DATE,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="file is missing",
            )
        },
        elapsed_ms=2,
    )


def _ready_batch():
    return ContinuityBatchReadiness(
        expected_trade_dates=(_TRADE_DATE,),
        statuses_by_trade_date={
            _TRADE_DATE: ContinuityDateReadiness(
                trade_date=_TRADE_DATE,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            )
        },
        elapsed_ms=2,
    )


def _reference(fingerprint_suffix="a"):
    code = f"BK000{1 if fingerprint_suffix == 'a' else 2}.DC"
    return build_dc_board_prod_reference_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=(("行业板块", code),),
        daily_identity=(("行业板块", code),),
        member_codes=(code,),
        member_row_count=1,
    )


def _reference_status(reference):
    return DcBoardProdReferenceResult(
        trade_date=_TRADE_DATE,
        ready=True,
        reason_code="ready",
        snapshot=reference,
        query_count=3,
        elapsed_ms=1.0,
    )


def _comparison(*, ready=True):
    return DcBoardTushareReferenceComparison(
        trade_date=_TRADE_DATE,
        ready=ready,
        reason_code="ready" if ready else "tushare_reference_mismatch",
        request_count=4,
        page_count=4,
        retry_count=0,
        elapsed_ms=2.0,
        index_rows_by_type={},
        daily_rows=(),
        daily_missing_count=0 if ready else 1,
    )


def _prepare_index(monkeypatch, *, reference, comparison=None):
    monkeypatch.setattr(dc_board_sensor, "_load_window", lambda *_args, **_kwargs: _window_and_gap())
    monkeypatch.setattr(dc_board_sensor, "batch_raw_dc_index_lake_readiness", lambda **_kwargs: _not_ready_batch())
    monkeypatch.setattr(dc_board_sensor, "load_prod_dc_board_reference", lambda **_kwargs: _reference_status(reference))
    if comparison is not None:
        monkeypatch.setattr(dc_board_sensor, "compare_tushare_index_and_daily_to_reference", lambda **_kwargs: comparison)


def test_index_sensor_skips_before_2115_without_prod_or_tushare_calls(monkeypatch):
    reference_calls = []
    _prepare_index(monkeypatch, reference=_reference())
    monkeypatch.setattr(
        dc_board_sensor,
        "load_prod_dc_board_reference",
        lambda **_kwargs: reference_calls.append(True),
    )
    evaluated_at = dc_board_sensor.datetime(2026, 7, 14, 21, 14, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE)

    result = dc_board_sensor._evaluate_index_sensor(_context(), evaluated_at=evaluated_at)

    assert not result.run_requests
    assert "before_prod_reference_window" in result.cursor
    assert not reference_calls


def test_index_sensor_requires_two_stable_prod_snapshots_then_submits_one_run(monkeypatch):
    reference = _reference()
    comparison = _comparison()
    _prepare_index(monkeypatch, reference=reference, comparison=comparison)
    first_at = dc_board_sensor.datetime(2026, 7, 14, 21, 16, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE)
    context = _context()

    first = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=first_at)
    assert not first.run_requests
    assert "prod_reference_pending_confirmation" in first.cursor
    runtime = json.loads(first.cursor)["details"]["runtime_state"]
    assert runtime["dc_board_prod_reference"]["fingerprint"] == reference.fingerprint
    assert "index_identity" not in first.cursor

    context.cursor = first.cursor
    second = dc_board_sensor._evaluate_index_sensor(
        context,
        evaluated_at=first_at + timedelta(seconds=301),
    )
    assert len(second.run_requests) == 1
    request = second.run_requests[0]
    assert request.partition_key == _TRADE_DATE
    assert request.run_config["ops"]["raw_tushare_dc_index"]["config"] == {
        "reference_trade_date": _TRADE_DATE,
        "reference_observed_at": (first_at + timedelta(seconds=301)).isoformat(),
        "reference_fingerprint": reference.fingerprint,
    }
    assert len(second.cursor.encode("utf-8")) < 3072


def test_index_sensor_restarts_confirmation_when_second_prod_snapshot_changes(monkeypatch):
    first_reference = _reference("a")
    second_reference = _reference("b")
    calls = iter((_reference_status(first_reference), _reference_status(second_reference)))
    _prepare_index(monkeypatch, reference=first_reference, comparison=_comparison())
    monkeypatch.setattr(dc_board_sensor, "load_prod_dc_board_reference", lambda **_kwargs: next(calls))
    first_at = dc_board_sensor.datetime(2026, 7, 14, 21, 16, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE)
    context = _context()
    first = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=first_at)
    context.cursor = first.cursor

    second = dc_board_sensor._evaluate_index_sensor(
        context,
        evaluated_at=first_at + timedelta(seconds=301),
    )

    assert not second.run_requests
    assert "prod_reference_changed" in second.cursor
    assert second_reference.fingerprint in second.cursor


def test_index_sensor_rejects_tushare_identity_mismatch_before_run_request(monkeypatch):
    reference = _reference()
    _prepare_index(monkeypatch, reference=reference, comparison=_comparison(ready=False))
    evaluated_at = dc_board_sensor.datetime(2026, 7, 15, 8, 0, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE)

    result = dc_board_sensor._evaluate_index_sensor(_context(), evaluated_at=evaluated_at)

    assert not result.run_requests
    assert "tushare_reference_mismatch" in result.cursor
    assert "tushare_dc_board" in result.cursor


def test_dependent_sensor_waits_only_for_same_day_index_not_source_probe(monkeypatch):
    monkeypatch.setattr(dc_board_sensor, "_load_window", lambda *_args, **_kwargs: _window_and_gap())
    monkeypatch.setattr(dc_board_sensor, "batch_raw_dc_daily_lake_readiness", lambda **_kwargs: _not_ready_batch())
    monkeypatch.setattr(dc_board_sensor, "batch_raw_dc_index_lake_readiness", lambda **_kwargs: _ready_batch())

    result = dc_board_sensor._evaluate_dependent_sensor(
        _context(),
        evaluated_at=dc_board_sensor.datetime(2026, 7, 15, 8, 0, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_daily_update_job_sensor",
        job_name="raw_tushare_dc_daily_update_job",
        min_trade_date="2024-01-02",
        batch_reader=dc_board_sensor.batch_raw_dc_daily_lake_readiness,
        partition_set="cn_a_dc_daily_trade_days",
    )

    assert len(result.run_requests) == 1
    assert result.run_requests[0].partition_key == _TRADE_DATE
    assert "source_probe" not in result.cursor
