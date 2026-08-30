from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from orchestrator.defs.assets.etf_mins import EtfMinsRawWriteError
from orchestrator.defs.bootstrap import etf_mins_bootstrap as bootstrap
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_raw,
    build_etf_mins_bootstrap_plan,
    compute_etf_mins_bootstrap_manifest_hash,
    compute_etf_mins_bootstrap_payload_hash,
    load_etf_mins_bootstrap_plan,
    operation_root_for_etf_mins_bootstrap,
    run_etf_mins_bootstrap_plan,
    write_etf_mins_bootstrap_plan,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_etf_mins_path, silver_etf_basic_snapshot_path
from orchestrator.defs.run_contracts.etf_mins import ETF_MINS_SOURCE_FREQS
from tests.etf_mins_bootstrap_support import (
    FakeProdPostgres,
    TestDuckDBResource,
    coverages,
    install_fake_prod_source,
    minute_row,
    roots,
    write_basic_pair,
    write_minute_file,
)


def _dates(count: int, *, start: date = date(2026, 1, 1)) -> tuple[str, ...]:
    return tuple(
        (start + timedelta(days=offset)).isoformat() for offset in range(count)
    )


def _build_plan(
    *,
    lake_root: Path,
    staging_root: Path,
    trade_dates: tuple[str, ...],
    operation_id: str = "bootstrap-test",
    free_bytes: int = 10**12,
):  # type: ignore[no-untyped-def]
    reference, targets = write_basic_pair(lake_root=lake_root)
    coverage_dates = trade_dates[-10:]
    return build_etf_mins_bootstrap_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id=operation_id,
        requested_start_date=trade_dates[0],
        requested_end_date=trade_dates[-1],
        created_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
        basic_reference=reference,  # type: ignore[arg-type]
        requestable_targets=targets,
        calendar_trade_dates=trade_dates,
        watermark_coverages=coverages(coverage_dates),
        free_bytes=free_bytes,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
    )


def _plan_paths(
    *,
    staging_root: Path,
    operation_id: str,
) -> tuple[Path, Path, Path]:
    operation_root = operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=operation_id,
    )
    return (
        operation_root / "plan.json",
        operation_root / "raw_checkpoint.json",
        operation_root / "raw_final_report.json",
    )


def test_plan_freezes_dynamic_watermark_query_file_and_disk_budgets(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = _dates(25)
    reference, targets = write_basic_pair(lake_root=lake_root)
    coverage_dates = trade_dates[-10:]
    incomplete_latest = {
        (trade_dates[-1], source_freq) for source_freq in ETF_MINS_SOURCE_FREQS
    }
    plan = build_etf_mins_bootstrap_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id="watermark-plan",
        requested_start_date=trade_dates[0],
        requested_end_date=trade_dates[-1],
        created_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
        basic_reference=reference,  # type: ignore[arg-type]
        requestable_targets=targets,
        calendar_trade_dates=trade_dates,
        watermark_coverages=coverages(
            coverage_dates,
            incomplete=incomplete_latest,
        ),
        free_bytes=10**12,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
    )

    assert plan.execution_watermark_date == trade_dates[-2]
    assert plan.trimmed_trade_dates == (trade_dates[-1],)
    assert len(plan.expected_trade_dates) == 24
    assert plan.target_file_count == 120
    assert plan.plan_coverage_query_count == 1
    assert plan.raw_detail_query_count == 10
    assert plan.expected_remote_query_count == 11
    assert plan.preexisting_target_state_summary == {
        "missing": 120,
        "present_structurally_valid_uncompared": 0,
        "present_invalid": 0,
    }
    assert plan.should_stop is False
    assert {str(row["state"]) for row in plan.preexisting_target_manifest} == {
        "missing"
    }
    assert "reused" not in json.dumps(plan.to_dict())
    assert "conflict-stop" not in json.dumps(plan.to_dict())

    plan_path, _, _ = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    assert (
        load_etf_mins_bootstrap_plan(
            plan_path,
            staging_root=staging_root,
        )
        == plan
    )


def test_plan_entrypoint_executes_exactly_one_bounded_coverage_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = _dates(12)
    reference, _ = write_basic_pair(lake_root=lake_root)
    observed_coverage_dates: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        bootstrap,
        "select_latest_etf_basic_snapshot_reference",
        lambda **_: reference,
    )
    monkeypatch.setattr(
        bootstrap,
        "load_etf_mins_bootstrap_trade_dates",
        lambda **_: trade_dates,
    )

    def fake_coverage(**kwargs):  # type: ignore[no-untyped-def]
        observed_coverage_dates.append(tuple(kwargs["trade_dates"]))
        return coverages(kwargs["trade_dates"])

    monkeypatch.setattr(bootstrap, "load_prod_etf_mins_code_coverage", fake_coverage)
    report_path = (
        operation_root_for_etf_mins_bootstrap(
            staging_root=staging_root,
            operation_id="plan-entrypoint",
        )
        / "plan.json"
    )
    plan = run_etf_mins_bootstrap_plan(
        instance=object(),
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        requested_start_date=trade_dates[0],
        requested_end_date=trade_dates[-1],
        report_path=report_path,
        created_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
    )

    assert observed_coverage_dates == [trade_dates[-10:]]
    assert plan.plan_coverage_query_count == 1
    assert plan.execution_watermark_date == trade_dates[-1]
    assert report_path.is_file()


def test_plan_hashes_logical_content_and_disk_failure_is_frozen(
    tmp_path: Path,
) -> None:
    first = {"b": 2, "a": [3, 1]}
    second = {"a": [3, 1], "b": 2}
    assert compute_etf_mins_bootstrap_payload_hash(first) == (
        compute_etf_mins_bootstrap_payload_hash(second)
    )
    rows = (
        {"source_freq": "5min", "trade_date": "2026-01-02", "value": 2},
        {"source_freq": "1min", "trade_date": "2026-01-01", "value": 1},
    )
    assert compute_etf_mins_bootstrap_manifest_hash(
        rows,
        key_fields=("source_freq", "trade_date"),
    ) == compute_etf_mins_bootstrap_manifest_hash(
        tuple(reversed(rows)),
        key_fields=("source_freq", "trade_date"),
    )
    changed = (rows[0], {**rows[1], "value": 9})
    assert compute_etf_mins_bootstrap_manifest_hash(
        rows,
        key_fields=("source_freq", "trade_date"),
    ) != compute_etf_mins_bootstrap_manifest_hash(
        changed,
        key_fields=("source_freq", "trade_date"),
    )

    lake_root, staging_root = roots(tmp_path)
    stopped = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=_dates(2),
        operation_id="disk-stop",
        free_bytes=0,
    )
    assert stopped.should_stop is True
    assert stopped.stop_reasons == ("etf_mins_bootstrap_disk_budget_insufficient",)


def test_plan_stops_when_the_five_frequency_target_budget_is_exceeded(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = _dates(2_001)
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=trade_dates,
        operation_id="target-budget-stop",
    )
    assert plan.target_file_count == 10_005
    assert plan.should_stop is True
    assert "etf_mins_bootstrap_target_file_budget_exceeded" in plan.stop_reasons


def test_raw_apply_uses_one_query_per_twenty_day_frequency_batch_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = _dates(21)
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=trade_dates,
        operation_id="raw-resume",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    rows = [
        minute_row(source_freq=source_freq, trade_date=trade_date)
        for source_freq in ETF_MINS_SOURCE_FREQS
        for trade_date in trade_dates
    ]
    source_calls = install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=rows,
    )
    original_apply_target = bootstrap._apply_one_etf_mins_raw_target
    call_count = 0

    def interrupt_second_target(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise EtfMinsBootstrapError("injected_after_first_checkpoint")
        return original_apply_target(**kwargs)

    monkeypatch.setattr(
        bootstrap,
        "_apply_one_etf_mins_raw_target",
        interrupt_second_target,
    )
    with pytest.raises(EtfMinsBootstrapError, match="injected_after_first_checkpoint"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert len(source_calls) == 1
    assert not report_path.exists()
    assert (
        len(list(plan_path.parent.glob("raw/source_batches/**/part-000.parquet"))) == 1
    )
    monkeypatch.setattr(
        bootstrap,
        "_apply_one_etf_mins_raw_target",
        original_apply_target,
    )

    report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert len(source_calls) == 10
    assert report.actual_remote_query_count == plan.raw_detail_query_count == 10
    assert report.added_file_count == 105
    assert report.reused_file_count == 0
    assert report.zero_row_file_count == 0
    assert report.source_row_count == 105
    assert report.formal_raw_row_count == 105
    assert report.temporary_space_peak_bytes > 0
    assert report.final_space_increment_bytes > 0
    assert report.finalized_raw_manifest_path.is_file()
    assert not list(plan_path.parent.glob("raw/source_batches/**/part-000.parquet"))
    checkpoint_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(checkpoint_payload["source_batches"]) == 10
    assert all(
        batch["batch_completed"] is True
        and batch["completed_target_count"] in {1, 20}
        and batch["temporary_space_peak_bytes"] >= batch["source_file_size_bytes"]
        and batch["staging_row_count"] == batch["formal_raw_row_count"]
        and batch["promoted_file_count"] + batch["reused_file_count"]
        == batch["completed_target_count"]
        for batch in checkpoint_payload["source_batches"].values()
    )
    assert all(
        raw_etf_mins_path(lake_root, source_freq, trade_date).is_file()
        for source_freq in ETF_MINS_SOURCE_FREQS
        for trade_date in trade_dates
    )

    same_report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert same_report.report_hash == report.report_hash
    assert len(source_calls) == 10


def test_raw_apply_creates_explicit_zero_rows_and_rejects_unassigned_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = ("2026-01-02", "2026-01-05")
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=trade_dates,
        operation_id="zero-rows",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    source_calls = install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_dates[0])
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
    )
    report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert len(source_calls) == 5
    assert report.zero_row_file_count == 5

    bad_lake_root, bad_staging_root = roots(tmp_path / "bad")
    bad_plan = _build_plan(
        lake_root=bad_lake_root,
        staging_root=bad_staging_root,
        trade_dates=trade_dates,
        operation_id="unexpected-date",
    )
    bad_plan_path, bad_checkpoint_path, bad_report_path = _plan_paths(
        staging_root=bad_staging_root,
        operation_id=bad_plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(bad_plan_path, bad_plan)
    install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[minute_row(source_freq="1min", trade_date="2026-01-03")],
    )
    with pytest.raises(EtfMinsBootstrapError, match="source_scope_invalid"):
        apply_etf_mins_bootstrap_raw(
            lake_root=bad_lake_root,
            staging_root=bad_staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=bad_plan_path,
            checkpoint_path=bad_checkpoint_path,
            raw_final_report_path=bad_report_path,
            confirm_raw_lake_write=True,
        )
    assert not bad_report_path.exists()
    assert not any(
        raw_etf_mins_path(bad_lake_root, source_freq, trade_date).exists()
        for source_freq in ETF_MINS_SOURCE_FREQS
        for trade_date in trade_dates
    )


def test_raw_apply_requires_confirmation_and_never_mentions_downstream_writes(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=_dates(1),
        operation_id="confirm",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    with pytest.raises(EtfMinsBootstrapError, match="confirmation_required"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=False,
        )
    source = Path(bootstrap.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "report_runless_asset_event",
        "add_dynamic_partitions",
        "silver_eligible=true",
        "@dg.asset",
        "@dg.sensor",
        "ops.task_run",
        "core_serving",
    ):
        assert forbidden not in source


def test_plan_only_prechecks_existing_target_and_apply_stops_on_content_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    target_path = raw_etf_mins_path(lake_root, "1min", trade_date)
    write_minute_file(
        target_path,
        [minute_row(source_freq="1min", trade_date=trade_date, close=12.0)],
    )
    original_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="target-conflict",
    )
    state_by_freq = {
        str(row["source_freq"]): str(row["state"])
        for row in plan.preexisting_target_manifest
    }
    assert state_by_freq["1min"] == "present_structurally_valid_uncompared"
    assert plan.should_stop is False
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
    )
    with pytest.raises(EtfMinsBootstrapError, match="target_conflict"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert hashlib.sha256(target_path.read_bytes()).hexdigest() == original_hash
    assert not report_path.exists()


def test_plan_stops_when_one_existing_target_has_a_per_file_schema_drift(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    target_path = raw_etf_mins_path(lake_root, "1min", trade_date)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with TestDuckDBResource().connect() as connection:
        connection.execute(
            copy_query_to_parquet(
                """
                SELECT
                  '510300.SH'::VARCHAR AS ts_code,
                  '1min'::VARCHAR AS freq,
                  TIMESTAMP '2026-01-02 09:31:00' AS trade_time,
                  10.0::DOUBLE AS open,
                  10.1::DOUBLE AS close,
                  10.2::DOUBLE AS high,
                  9.9::DOUBLE AS low,
                  100::BIGINT AS vol,
                  1000.0::DOUBLE AS amount,
                  'XSHG'::VARCHAR AS exchange
                """,
                target_path,
            )
        )

    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="schema-drift",
    )
    target = next(
        row for row in plan.preexisting_target_manifest if row["source_freq"] == "1min"
    )
    assert target["state"] == "present_invalid"
    assert target["reason_code"] == "etf_mins_target_schema_invalid"
    assert plan.should_stop is True
    assert "etf_mins_bootstrap_existing_raw_invalid" in plan.stop_reasons


def test_plan_accepts_a_schema_correct_explicit_zero_row_raw_file(
    tmp_path: Path,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    write_minute_file(raw_etf_mins_path(lake_root, "1min", trade_date), [])

    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="zero-row-precheck",
    )
    target = next(
        row for row in plan.preexisting_target_manifest if row["source_freq"] == "1min"
    )
    assert target["state"] == "present_structurally_valid_uncompared"
    assert target["row_count"] == 0
    assert target["reason_code"] is None
    assert plan.should_stop is False


def test_raw_apply_reuses_equivalent_targets_and_final_report_is_relocatable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    source_rows = [
        minute_row(source_freq=source_freq, trade_date=trade_date)
        for source_freq in ETF_MINS_SOURCE_FREQS
    ]
    for source_freq, row in zip(ETF_MINS_SOURCE_FREQS, source_rows, strict=True):
        write_minute_file(raw_etf_mins_path(lake_root, source_freq, trade_date), [row])
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="equivalent-reuse",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    source_calls = install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=source_rows,
    )

    report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert report.added_file_count == 0
    assert report.reused_file_count == 5
    assert report.final_space_increment_bytes == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["finalized_raw_manifest_relative_path"] == (
        "finalized_raw_manifest.parquet"
    )
    assert "finalized_raw_manifest_path" not in payload
    assert str(staging_root) not in report_path.read_text(encoding="utf-8")

    changed_path = raw_etf_mins_path(lake_root, "1min", trade_date)
    write_minute_file(
        changed_path,
        [minute_row(source_freq="1min", trade_date=trade_date, close=12.0)],
    )
    with pytest.raises(EtfMinsBootstrapError, match="finalized_raw_file_changed"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert len(source_calls) == 5


def test_raw_apply_stops_before_the_next_prod_batch_when_basic_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_dates = _dates(21)
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=trade_dates,
        operation_id="basic-drift",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    source_calls = install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
            for trade_date in trade_dates
        ],
    )
    original_revalidate = bootstrap.revalidate_etf_mins_basic_reference
    revalidation_count = 0

    def drift_before_second_batch(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal revalidation_count
        revalidation_count += 1
        if revalidation_count == 2:
            frozen_silver_path = silver_etf_basic_snapshot_path(
                lake_root,
                plan.basic_raw_snapshot_hash,
            )
            frozen_silver_path.unlink()
        return original_revalidate(**kwargs)

    monkeypatch.setattr(
        bootstrap,
        "revalidate_etf_mins_basic_reference",
        drift_before_second_batch,
    )
    with pytest.raises(EtfMinsRawWriteError, match="basic_reference_invalid"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert len(source_calls) == 1
    assert not report_path.exists()


def test_raw_apply_can_finalize_from_checkpoint_after_completed_batches_are_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="finalize-resume",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    source_calls = install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
    )
    original_finalize = bootstrap._write_or_validate_finalized_raw_manifest

    def fail_before_final_report(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise EtfMinsBootstrapError("injected_before_final_report")

    monkeypatch.setattr(
        bootstrap,
        "_write_or_validate_finalized_raw_manifest",
        fail_before_final_report,
    )
    with pytest.raises(EtfMinsBootstrapError, match="injected_before_final_report"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )
    assert len(source_calls) == 5
    assert not report_path.exists()
    assert not list(plan_path.parent.glob("raw/source_batches/**/part-000.parquet"))

    monkeypatch.setattr(
        bootstrap,
        "_write_or_validate_finalized_raw_manifest",
        original_finalize,
    )
    report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert len(source_calls) == 5
    assert report.added_file_count == 5
    assert report.actual_remote_query_count == 5


def test_raw_apply_reuses_an_empty_batch_directory_after_a_prequery_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root = roots(tmp_path)
    trade_date = "2026-01-02"
    plan = _build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        trade_dates=(trade_date,),
        operation_id="empty-batch-retry",
    )
    plan_path, checkpoint_path, report_path = _plan_paths(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    )
    write_etf_mins_bootstrap_plan(plan_path, plan)
    install_fake_prod_source(
        bootstrap,
        monkeypatch,
        rows=[
            minute_row(source_freq=source_freq, trade_date=trade_date)
            for source_freq in ETF_MINS_SOURCE_FREQS
        ],
    )
    fake_attach = bootstrap._attach_prod_etf_mins_readonly
    attach_attempts = 0

    def fail_first_attach(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal attach_attempts
        attach_attempts += 1
        if attach_attempts == 1:
            raise EtfMinsBootstrapError("injected_prequery_failure")
        return fake_attach(*args, **kwargs)

    monkeypatch.setattr(
        bootstrap,
        "_attach_prod_etf_mins_readonly",
        fail_first_attach,
    )
    with pytest.raises(EtfMinsBootstrapError, match="injected_prequery_failure"):
        apply_etf_mins_bootstrap_raw(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            raw_final_report_path=report_path,
            confirm_raw_lake_write=True,
        )

    report = apply_etf_mins_bootstrap_raw(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
        prod_postgres=FakeProdPostgres(),  # type: ignore[arg-type]
        plan_path=plan_path,
        checkpoint_path=checkpoint_path,
        raw_final_report_path=report_path,
        confirm_raw_lake_write=True,
    )
    assert report.actual_remote_query_count == 5
    assert attach_attempts == 6
