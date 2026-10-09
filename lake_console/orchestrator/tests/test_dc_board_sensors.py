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
    DcBoardProdCompletionResult,
    DcBoardTushareSourceResult,
)
from orchestrator.defs.run_contracts.dc_board import (
    build_dc_board_prod_completion_snapshot,
    build_dc_board_tushare_source_snapshot,
)
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
    return (
        window,
        tuple(registered),
        build_registered_gap_status(
            expected_trade_dates=window.expected_trade_dates,
            registered_trade_dates=registered,
        ),
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


def _completion(fingerprint_suffix="a"):
    code = f"BK000{1 if fingerprint_suffix == 'a' else 2}.DC"
    return build_dc_board_prod_completion_snapshot(
        trade_date=_TRADE_DATE,
        index_identity=(("行业板块", code),),
        daily_identity=(("行业板块", code),),
        member_codes=(code,),
        member_row_count=1,
    )


def _completion_status(completion):
    return DcBoardProdCompletionResult(
        trade_date=_TRADE_DATE,
        ready=True,
        reason_code="ready",
        snapshot=completion,
        query_count=3,
        elapsed_ms=1.0,
    )


def _source_result(*, ready=True, matches_prod=True, source_suffix="a"):
    snapshot = (
        build_dc_board_tushare_source_snapshot(
            trade_date=_TRADE_DATE,
            index_rows=(
                {
                    "idx_type": "行业板块",
                    "ts_code": "BK0001.DC",
                    "trade_date": _TRADE_DATE.replace("-", ""),
                    "name": source_suffix,
                },
            ),
            daily_rows=(
                {
                    "category": "行业板块",
                    "ts_code": "BK0001.DC",
                    "trade_date": _TRADE_DATE.replace("-", ""),
                    "close": 1.0,
                },
            ),
        )
        if ready
        else None
    )
    return DcBoardTushareSourceResult(
        trade_date=_TRADE_DATE,
        ready=ready,
        reason_code="ready" if ready else "source_validation_failed",
        request_count=4,
        page_count=4,
        retry_count=0,
        elapsed_ms=2.0,
        snapshot=snapshot,
        index_rows_by_type={},
        daily_rows=(),
        daily_missing_count=0 if matches_prod else 1,
    )


def _prepare_index(monkeypatch, *, observe):
    monkeypatch.setattr(dc_board_sensor, "_load_window", lambda *_args, **_kwargs: _window_and_gap())
    monkeypatch.setattr(dc_board_sensor, "batch_raw_dc_index_lake_readiness", lambda **_kwargs: _not_ready_batch())
    monkeypatch.setattr(dc_board_sensor, "observe_dc_board_source", observe)


def test_index_sensor_skips_before_2115_without_source_calls(monkeypatch):
    calls = []
    _prepare_index(monkeypatch, observe=lambda **_: calls.append(True))
    moment = dc_board_sensor.datetime(2026, 7, 14, 21, 14, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE)
    result = dc_board_sensor._evaluate_index_sensor(_context(), evaluated_at=moment)
    assert not result.run_requests and "current_day_reference_not_before" in result.cursor
    assert not calls


def test_index_sensor_freezes_one_run_after_stable_completed_observations(monkeypatch):
    from tests.test_dc_board_source_freeze import START, observation
    moments = iter((START, START + timedelta(seconds=299), START + timedelta(seconds=300)))
    _prepare_index(monkeypatch, observe=lambda **_: observation(next(moments)))
    context = _context()
    first = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=START.astimezone(dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    assert not first.run_requests and "source_confirmation_pending" in first.cursor
    context.cursor = first.cursor
    second = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=(START + timedelta(seconds=299)).astimezone(dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    assert not second.run_requests
    context.cursor = second.cursor
    third = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=(START + timedelta(seconds=300)).astimezone(dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    assert len(third.run_requests) == 1
    proof = third.run_requests[0].run_config["ops"]["raw_tushare_dc_index"]["config"]
    assert proof["prod_observed_at_first"] == START.isoformat()
    assert proof["target_asset"] == "raw_tushare_dc_index"
    assert "index_identity" not in third.cursor and len(third.cursor.encode()) < 4096


def test_index_sensor_restarts_when_source_changes(monkeypatch):
    from dataclasses import replace

    from tests.test_dc_board_raw_io import _source_result
    from tests.test_dc_board_source_freeze import START, observation
    observations = iter((observation(gap=True), replace(observation(START + timedelta(seconds=600), gap=True), source=_source_result(close=11))))
    _prepare_index(monkeypatch, observe=lambda **_: next(observations))
    context = _context()
    first = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=START.astimezone(dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    context.cursor = first.cursor
    second = dc_board_sensor._evaluate_index_sensor(context, evaluated_at=(START + timedelta(seconds=600)).astimezone(dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    assert not second.run_requests
    state = json.loads(second.cursor)["details"]["runtime_state"]["dc_board_source_freeze"]
    assert state["source_observed_at"] == (START + timedelta(seconds=600)).isoformat()


def test_dependent_sensor_requires_own_gap_pair_after_same_day_index_ready(monkeypatch):
    from tests.test_dc_board_source_freeze import START, observation
    observations = iter((observation(gap=True), observation(START + timedelta(seconds=300), gap=True)))
    _prepare_index(monkeypatch, observe=lambda **_: next(observations))
    monkeypatch.setattr(dc_board_sensor, "batch_raw_dc_index_lake_readiness", lambda **_: _ready_batch())
    context = _context()
    kwargs = {"sensor_name": "raw_tushare_dc_daily_update_job_sensor", "job_name": "raw_tushare_dc_daily_update_job",
        "min_trade_date": "2024-01-02", "batch_reader": lambda **_: _not_ready_batch(), "partition_set": "cn_a_dc_daily_trade_days"}
    first = dc_board_sensor._evaluate_dependent_sensor(context, evaluated_at=START, **kwargs)
    assert not first.run_requests
    context.cursor = first.cursor
    second = dc_board_sensor._evaluate_dependent_sensor(context, evaluated_at=START + timedelta(seconds=300), **kwargs)
    assert len(second.run_requests) == 1
    proof = second.run_requests[0].run_config["ops"]["raw_tushare_dc_daily"]["config"]
    assert proof["prod_observed_at_first"] is None and proof["source_observed_at_first"]


def test_source_exception_never_submits_or_retains_a_stale_proof(monkeypatch):
    def observe(**_):
        raise ValueError("source unavailable")
    _prepare_index(monkeypatch, observe=observe)
    result = dc_board_sensor._evaluate_index_sensor(_context(cursor="{}"), evaluated_at=dc_board_sensor.datetime(2026, 7, 15, 8, tzinfo=dc_board_sensor.CN_A_SENSOR_TIMEZONE))
    assert not result.run_requests and "source unavailable" in str(result.skip_reason)
    assert "dc_board_source_freeze" not in json.loads(result.cursor)["details"].get("runtime_state", {})
