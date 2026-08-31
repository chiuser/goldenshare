from __future__ import annotations

from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    load_etf_mins_bar_domain_check_evidence,
    load_etf_mins_raw_materialization_evidence,
    load_etf_mins_silver_materialization_evidence,
)
from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    SILVER_ETF_MINS_ASSETS,
)
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    apply_etf_mins_bootstrap_events,
    audit_etf_mins_bootstrap_events,
    plan_etf_mins_bootstrap_events,
    plan_etf_mins_bootstrap_partitions,
    register_etf_mins_bootstrap_partitions,
)
from orchestrator.defs.paths import silver_etf_mins_path
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_RAW_APPROVED_POLICY_VERSION,
    get_etf_mins_raw_decision_policy,
)
from tests.etf_mins_bootstrap_support import TestDuckDBResource
from tests.test_etf_mins_raw_decision import _canonical_rows
from tests.test_etf_mins_silver_bootstrap import _apply, _decision_operation


def _completed_operation(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation_id: str,
    trade_dates: tuple[str, ...],
    blocked: bool = False,
):  # type: ignore[no-untyped-def]
    policy = get_etf_mins_raw_decision_policy(ETF_MINS_RAW_APPROVED_POLICY_VERSION)
    rows = []
    for index, trade_date in enumerate(trade_dates):
        rows.extend(
            _canonical_rows(
                policy=policy,
                trade_date=trade_date,
                missing_clock=("5min", "10:00:00") if blocked and index == 0 else None,
                invalid_price=("1min", "09:30:00") if blocked and index == 0 else None,
            )
        )
    operation_root, decision = _decision_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id=operation_id,
        trade_dates=trade_dates,
        rows=rows,
    )
    report = _apply(
        tmp_path=tmp_path,
        operation_root=operation_root,
        decision=decision,
    )
    return (
        tmp_path / "data_lake",
        tmp_path / "data_lake_staging",
        report.final_report_path,
    )


def test_partition_registration_is_explicit_bounded_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, staging_root, final_report_path = _completed_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="event-partitions",
        trade_dates=("2026-01-02", "2026-01-05"),
    )
    instance = dg.DagsterInstance.ephemeral()
    try:
        dry_run = plan_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            final_report_path=final_report_path,
        )
        assert dry_run.planned_partition_count == 2
        assert dry_run.missing_partition_count == 2
        with pytest.raises(EtfMinsBootstrapError, match="confirmation_required"):
            register_etf_mins_bootstrap_partitions(
                instance=instance,
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
                final_report_path=final_report_path,
                confirm_partition_write=False,
            )
        applied = register_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_partition_write=True,
        )
        assert applied.added_partition_count == 2
        assert applied.missing_partition_count == 0
        repeated = register_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=TestDuckDBResource(),  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_partition_write=True,
        )
        assert repeated.added_partition_count == 0
        assert all(
            not instance.get_materialized_partitions(asset.key)
            for asset in (*RAW_ETF_MINS_ASSETS, *SILVER_ETF_MINS_ASSETS)
        )
    finally:
        instance.dispose()


def test_events_are_exact_idempotent_and_bound_to_materializations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_dates = ("2026-01-02", "2026-01-05")
    lake_root, staging_root, final_report_path = _completed_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="event-green",
        trade_dates=trade_dates,
    )
    instance = dg.DagsterInstance.ephemeral()
    duckdb = TestDuckDBResource()
    try:
        with pytest.raises(EtfMinsBootstrapError, match="partitions_not_registered"):
            plan_etf_mins_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,  # type: ignore[arg-type]
                final_report_path=final_report_path,
            )
        register_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_partition_write=True,
        )
        dry_run = plan_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
        )
        assert dry_run.raw_materialization_count == 10
        assert dry_run.silver_materialization_count == 10
        assert dry_run.pending_materialization_count == 20
        assert dry_run.planned_check_event_count == 50
        assert dry_run.pending_check_event_count == 50
        assert dry_run.materialization_query_count == 10
        assert dry_run.check_history_query_count == 25
        with pytest.raises(EtfMinsBootstrapError, match="confirmation_required"):
            apply_etf_mins_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,  # type: ignore[arg-type]
                final_report_path=final_report_path,
                confirm_event_write=False,
            )
        applied = apply_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_event_write=True,
        )
        assert applied.reported_materialization_count == 20
        assert applied.reported_check_event_count == 50
        assert applied.pending_materialization_count == 0
        assert applied.pending_check_event_count == 0

        raw_evidence = load_etf_mins_raw_materialization_evidence(
            instance=instance,
            lake_root=lake_root,
            asset_key=RAW_ETF_MINS_ASSETS[0].key,
            partition_key=trade_dates[-1],
            source_freq="1min",
        )
        bar_evidence = load_etf_mins_bar_domain_check_evidence(
            instance=instance,
            raw_evidence=raw_evidence,
        )
        silver_evidence = load_etf_mins_silver_materialization_evidence(
            instance=instance,
            lake_root=lake_root,
            asset_key=SILVER_ETF_MINS_ASSETS[0].key,
            partition_key=trade_dates[-1],
            source_freq="1min",
        )
        assert bar_evidence.raw_storage_id == raw_evidence.storage_id
        assert silver_evidence.raw_sha256 == raw_evidence.raw_sha256

        repeated = plan_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
        )
        assert repeated.pending_materialization_count == 0
        assert repeated.pending_check_event_count == 0
        audited = audit_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
        )
        assert audited.sample_trade_dates == trade_dates
    finally:
        instance.dispose()


def test_blocked_raw_gets_failed_bar_check_and_no_silver_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = "2026-01-02"
    lake_root, staging_root, final_report_path = _completed_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="event-blocked",
        trade_dates=(trade_date,),
        blocked=True,
    )
    instance = dg.DagsterInstance.ephemeral()
    duckdb = TestDuckDBResource()
    try:
        register_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_partition_write=True,
        )
        plan = plan_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
        )
        assert plan.raw_materialization_count == 5
        assert plan.silver_materialization_count == 3
        assert plan.planned_check_event_count == 21
        apply_etf_mins_bootstrap_events(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_event_write=True,
        )
        assert trade_date not in instance.get_materialized_partitions(
            SILVER_ETF_MINS_ASSETS[0].key
        )
        raw_evidence = load_etf_mins_raw_materialization_evidence(
            instance=instance,
            lake_root=lake_root,
            asset_key=RAW_ETF_MINS_ASSETS[0].key,
            partition_key=trade_date,
            source_freq="1min",
        )
        with pytest.raises(RuntimeError, match="check_not_passed"):
            load_etf_mins_bar_domain_check_evidence(
                instance=instance,
                raw_evidence=raw_evidence,
            )
    finally:
        instance.dispose()


def test_event_dry_run_stops_on_file_drift_or_non_equivalent_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_date = "2026-01-02"
    lake_root, staging_root, final_report_path = _completed_operation(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        operation_id="event-conflict",
        trade_dates=(trade_date,),
    )
    instance = dg.DagsterInstance.ephemeral()
    duckdb = TestDuckDBResource()
    try:
        register_etf_mins_bootstrap_partitions(
            instance=instance,
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,  # type: ignore[arg-type]
            final_report_path=final_report_path,
            confirm_partition_write=True,
        )
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=RAW_ETF_MINS_ASSETS[0].key,
                partition=trade_date,
                metadata={"source_method": "unrelated"},
            )
        )
        with pytest.raises(EtfMinsBootstrapError, match="event_conflict"):
            plan_etf_mins_bootstrap_events(
                instance=instance,
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,  # type: ignore[arg-type]
                final_report_path=final_report_path,
            )
    finally:
        instance.dispose()

    changed_silver = silver_etf_mins_path(lake_root, "1min", trade_date)
    changed_silver.write_bytes(b"changed")
    clean_instance = dg.DagsterInstance.ephemeral()
    try:
        with pytest.raises(EtfMinsBootstrapError, match="silver_file_changed"):
            plan_etf_mins_bootstrap_partitions(
                instance=clean_instance,
                lake_root=lake_root,
                staging_root=staging_root,
                duckdb=duckdb,  # type: ignore[arg-type]
                final_report_path=final_report_path,
            )
    finally:
        clean_instance.dispose()
