from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from inspect import getsource, signature
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    build_registered_gap_status,
)
from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsRawMaterializationBatchEvidence,
)
from orchestrator.defs.asset_guards.etf_mins_prod_readiness import (
    EtfMinsProdSourceReadiness,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRequestableTarget,
    build_etf_mins_prod_coverage_reference,
    compute_etf_mins_expected_code_hash,
)
from orchestrator.defs.sensors import etf_mins_sensor
from orchestrator.defs.sensors.etf_basic_sensor import (
    raw_etf_basic_update_job_sensor,
    silver_etf_basic_update_job_sensor,
)
from orchestrator.defs.sensors.etf_mins_partition_sensor import (
    etf_mins_trade_day_sensor,
)
from orchestrator.defs.sensors.etf_mins_sensor import (
    evaluate_raw_etf_mins_sensor,
    evaluate_silver_etf_mins_sensor,
    raw_etf_mins_update_job_sensor,
    silver_etf_mins_update_job_sensor,
)

TRADE_DATE = "2026-08-28"
NOW = datetime(2026, 8, 31, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeDuckDBResource:
    @contextmanager
    def connect(self):  # type: ignore[no-untyped-def]
        yield object()


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        instance=SimpleNamespace(),
        resources=SimpleNamespace(
            duckdb=FakeDuckDBResource(),
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/isolated/lake"),
            ),
            prod_postgres=object(),
        ),
    )


def _window() -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=(TRADE_DATE,),
        min_trade_date="2026-01-01",
        max_trade_date=TRADE_DATE,
        evaluated_at=NOW,
        window_limit=10,
    )


def _lineage() -> EtfMinsRawMaterializationBatchEvidence:
    return EtfMinsRawMaterializationBatchEvidence(
        expected_partition_keys=(TRADE_DATE,),
        evidences_by_partition_and_freq={},
        missing_partition_and_freqs=tuple(
            (TRADE_DATE, source_freq) for source_freq in ETF_MINS_SOURCE_FREQS
        ),
        materialization_query_count=5,
    )


def _batch(*, ready: bool, materialized: bool) -> ContinuityBatchReadiness:
    return ContinuityBatchReadiness(
        expected_trade_dates=(TRADE_DATE,),
        statuses_by_trade_date={
            TRADE_DATE: ContinuityDateReadiness(
                trade_date=TRADE_DATE,
                ready=ready,
                materialized=materialized,
                checks_passed=ready,
                reason="ready" if ready else "missing",
            )
        },
        elapsed_ms=1,
        scanned_file_count=5 if materialized else 0,
    )


def _basic_reference():  # type: ignore[no-untyped-def]
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="a" * 64,
        silver_content_hash="b" * 64,
        raw_uri="/isolated/raw-basic.parquet",
        silver_uri="/isolated/silver-basic.parquet",
        raw_observed_at="2026-08-31T08:00:00+08:00",
        silver_observed_at="2026-08-31T08:01:00+08:00",
        eligibility_as_of="2026-08-31",
        requestable_code_count=1,
        requestable_code_hash="c" * 64,
    )


def test_all_five_etf_sensors_are_stopped_by_default() -> None:
    sensors = (
        etf_mins_trade_day_sensor,
        raw_etf_basic_update_job_sensor,
        silver_etf_basic_update_job_sensor,
        raw_etf_mins_update_job_sensor,
        silver_etf_mins_update_job_sensor,
    )
    assert all(
        sensor.default_status is dg.DefaultSensorStatus.STOPPED for sensor in sensors
    )


def test_raw_sensor_uses_one_coverage_result_after_batch_readiness(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    window = _window()
    gap = build_registered_gap_status(
        expected_trade_dates=(TRADE_DATE,),
        registered_trade_dates=(TRADE_DATE,),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "_load_window_and_lineage",
        lambda *args, **kwargs: (window, (TRADE_DATE,), gap, _lineage()),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "batch_etf_mins_raw_lake_readiness",
        lambda **kwargs: _batch(ready=False, materialized=False),
    )
    reference = _basic_reference()
    target = EtfMinsRequestableTarget(
        ts_code="510300.SH",
        list_date=date(2012, 5, 28),
        exchange="SH",
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "select_latest_etf_basic_snapshot_reference",
        lambda **kwargs: reference,
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "revalidate_etf_mins_basic_reference",
        lambda **kwargs: (reference, (target,)),
    )
    coverage = build_etf_mins_prod_coverage_reference(
        trade_date=TRADE_DATE,
        basic_reference_fingerprint=reference.reference_fingerprint,
        expected_code_count=1,
        expected_code_hash=compute_etf_mins_expected_code_hash(
            (target,), trade_date=TRADE_DATE
        ),
        frequency_coverages=(
            (source_freq, 1, 1, 0) for source_freq in ETF_MINS_SOURCE_FREQS
        ),
        coverage_observed_at=NOW.isoformat(),
    )
    coverage_calls = 0

    def ready_source(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal coverage_calls
        coverage_calls += 1
        return EtfMinsProdSourceReadiness(
            ready=True,
            reason_code="prod_etf_mins_source_ready",
            coverage_status=None,
            coverage_reference=coverage,
        )

    monkeypatch.setattr(
        etf_mins_sensor,
        "etf_mins_prod_source_ready_for_trade_date",
        ready_source,
    )

    result = evaluate_raw_etf_mins_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]

    assert coverage_calls == 1
    assert len(result.run_requests or []) == 1
    assert result.run_requests[0].partition_key == TRADE_DATE
    assert len(result.cursor.encode("utf-8")) < 2048


def test_raw_sensor_does_not_query_prod_when_existing_raw_failed(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    window = _window()
    gap = build_registered_gap_status(
        expected_trade_dates=(TRADE_DATE,),
        registered_trade_dates=(TRADE_DATE,),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "_load_window_and_lineage",
        lambda *args, **kwargs: (window, (TRADE_DATE,), gap, _lineage()),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "batch_etf_mins_raw_lake_readiness",
        lambda **kwargs: _batch(ready=False, materialized=True),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "etf_mins_prod_source_ready_for_trade_date",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not query Prod")),
    )

    result = evaluate_raw_etf_mins_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]

    assert not result.run_requests
    assert "拒绝自动覆盖" in str(result.skip_reason)


def test_silver_sensor_stops_at_raw_failure_without_prod_access(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    context = _context()
    window = _window()
    gap = build_registered_gap_status(
        expected_trade_dates=(TRADE_DATE,),
        registered_trade_dates=(TRADE_DATE,),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "_load_window_and_lineage",
        lambda *args, **kwargs: (window, (TRADE_DATE,), gap, _lineage()),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "batch_etf_mins_raw_lake_readiness",
        lambda **kwargs: _batch(ready=False, materialized=True),
    )
    monkeypatch.setattr(
        etf_mins_sensor,
        "batch_etf_mins_silver_lake_readiness",
        lambda **kwargs: _batch(ready=False, materialized=False),
    )

    result = evaluate_silver_etf_mins_sensor(context, evaluated_at=NOW)  # type: ignore[arg-type]

    assert not result.run_requests
    assert "不越过" in str(result.skip_reason)


def test_minute_readiness_contract_has_no_check_history_or_instance_dependency() -> None:
    readiness_source = getsource(etf_mins_sensor.batch_etf_mins_raw_lake_readiness)
    silver_source = getsource(evaluate_silver_etf_mins_sensor)

    assert "get_asset_check_execution_history" not in readiness_source
    assert "fetch_materializations" not in readiness_source
    assert "instance" not in signature(
        etf_mins_sensor.batch_etf_mins_raw_lake_readiness
    ).parameters
    assert "prod_postgres" not in silver_source
    assert "etf_mins_prod_source_ready_for_trade_date" not in silver_source
