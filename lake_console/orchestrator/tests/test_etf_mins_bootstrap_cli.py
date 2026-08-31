from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.assets.etf_mins import EtfMinsRawWriteError
from orchestrator.defs.bootstrap import etf_mins_bootstrap_cli as cli
from orchestrator.defs.bootstrap.etf_mins_bootstrap import (
    EtfMinsBootstrapError,
    validate_etf_mins_bootstrap_operation_path,
)


def test_cli_exposes_seven_stages_and_keeps_p9_writes_explicit() -> None:
    parser = cli._build_parser()
    plan_args = parser.parse_args(
        [
            "plan",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-08-28",
            "--report-path",
            (
                "/Volumes/datasource/data_lake_staging/etf_mins/"
                "operation_id=example/plan.json"
            ),
        ]
    )
    assert plan_args.command == "plan"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "raw-apply",
                "--plan-path",
                "/tmp/plan.json",
                "--checkpoint-path",
                "/tmp/checkpoint.json",
                "--raw-final-report-path",
                "/tmp/raw_final_report.json",
            ]
        )
    raw_observe_args = parser.parse_args(
        [
            "raw-observe",
            "--raw-final-report-path",
            "/tmp/operation/raw_final_report.json",
            "--output-dir",
            "/tmp/operation/raw-observe",
        ]
    )
    assert raw_observe_args.command == "raw-observe"
    raw_decide_args = parser.parse_args(
        [
            "raw-decide",
            "--observation-summary-path",
            "/tmp/operation/raw-observe/raw_observation_summary.json",
            "--approved-policy-version",
            "etf_mins_gap_policy_v1",
            "--output-dir",
            "/tmp/operation",
        ]
    )
    assert raw_decide_args.command == "raw-decide"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "silver-apply",
                "--raw-decision-summary-path",
                "/tmp/operation/raw_decision_summary.json",
                "--decision-manifest-path",
                "/tmp/operation/raw_partition_decision_manifest.parquet",
                "--checkpoint-path",
                "/tmp/operation/silver_checkpoint.json",
                "--final-report-path",
                "/tmp/operation/physical_final_report.json",
            ]
        )
    silver_apply_args = parser.parse_args(
        [
            "silver-apply",
            "--raw-decision-summary-path",
            "/tmp/operation/raw_decision_summary.json",
            "--decision-manifest-path",
            "/tmp/operation/raw_partition_decision_manifest.parquet",
            "--checkpoint-path",
            "/tmp/operation/silver_checkpoint.json",
            "--final-report-path",
            "/tmp/operation/physical_final_report.json",
            "--confirm-silver-lake-write",
        ]
    )
    assert silver_apply_args.command == "silver-apply"
    final_report = "/tmp/operation/physical_final_report.json"
    partitions_dry_run = parser.parse_args(
        ["partitions", "--final-report-path", final_report]
    )
    assert partitions_dry_run.confirm_partition_write is False
    partitions_apply = parser.parse_args(
        [
            "partitions",
            "--final-report-path",
            final_report,
            "--confirm-partition-write",
        ]
    )
    assert partitions_apply.confirm_partition_write is True
    events_dry_run = parser.parse_args(["events", "--final-report-path", final_report])
    assert events_dry_run.confirm_event_write is False
    assert events_dry_run.post_audit is False
    events_apply = parser.parse_args(
        ["events", "--final-report-path", final_report, "--confirm-event-write"]
    )
    assert events_apply.confirm_event_write is True
    events_post_audit = parser.parse_args(
        ["events", "--final-report-path", final_report, "--post-audit"]
    )
    assert events_post_audit.post_audit is True
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "events",
                "--final-report-path",
                final_report,
                "--confirm-event-write",
                "--post-audit",
            ]
        )


def test_operation_paths_must_be_absolute_and_bound_to_one_operation(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "data_lake_staging"
    staging_root.mkdir()
    valid = staging_root / "etf_mins" / "operation_id=approved" / "raw_checkpoint.json"
    operation_root, operation_id = validate_etf_mins_bootstrap_operation_path(
        valid,
        staging_root=staging_root,
    )
    assert operation_id == "approved"
    assert operation_root.name == "operation_id=approved"
    with pytest.raises(EtfMinsBootstrapError, match="not_absolute"):
        validate_etf_mins_bootstrap_operation_path(
            Path("relative/plan.json"),
            staging_root=staging_root,
        )
    with pytest.raises(EtfMinsBootstrapError, match="operation_boundary_missing"):
        validate_etf_mins_bootstrap_operation_path(
            staging_root / "etf_mins" / "plan.json",
            staging_root=staging_root,
        )
    with pytest.raises(EtfMinsBootstrapError, match="operation_mismatch"):
        validate_etf_mins_bootstrap_operation_path(
            valid,
            staging_root=staging_root,
            expected_operation_id="different",
        )


def test_raw_apply_cli_passes_only_frozen_paths_and_explicit_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    operation_root = staging_root / "etf_mins" / "operation_id=approved-raw"
    plan_path = operation_root / "plan.json"
    checkpoint_path = operation_root / "raw_checkpoint.json"
    report_path = operation_root / "raw_final_report.json"
    captured: dict[str, object] = {}

    def fake_apply(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(
            operation_id="approved-raw",
            plan_fingerprint="a" * 64,
            plan_path=plan_path,
            checkpoint_path=checkpoint_path,
            finalized_raw_manifest_path=operation_root
            / "finalized_raw_manifest.parquet",
            finalized_raw_manifest_hash="b" * 64,
            raw_final_report_path=report_path,
            source_row_count=10,
            formal_raw_row_count=10,
            added_file_count=5,
            reused_file_count=0,
            zero_row_file_count=0,
            actual_remote_query_count=5,
            temporary_space_peak_bytes=1_024,
            final_space_increment_bytes=2_048,
            report_hash="c" * 64,
        )

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "apply_etf_mins_bootstrap_raw", fake_apply)
    assert (
        cli.main(
            [
                "raw-apply",
                "--plan-path",
                str(plan_path),
                "--checkpoint-path",
                str(checkpoint_path),
                "--raw-final-report-path",
                str(report_path),
                "--confirm-raw-lake-write",
            ]
        )
        == 0
    )
    assert captured["plan_path"] == plan_path
    assert captured["checkpoint_path"] == checkpoint_path
    assert captured["raw_final_report_path"] == report_path
    assert captured["confirm_raw_lake_write"] is True
    output = capsys.readouterr().out
    assert "approved-raw" in output
    assert str(plan_path) in output
    assert str(checkpoint_path) in output


def test_cli_reports_frozen_basic_drift_as_a_controlled_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    operation_root = staging_root / "etf_mins" / "operation_id=basic-drift"

    def fail_apply(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise EtfMinsRawWriteError("etf_mins_basic_reference_invalid")

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "apply_etf_mins_bootstrap_raw", fail_apply)
    result = cli.main(
        [
            "raw-apply",
            "--plan-path",
            str(operation_root / "plan.json"),
            "--checkpoint-path",
            str(operation_root / "raw_checkpoint.json"),
            "--raw-final-report-path",
            str(operation_root / "raw_final_report.json"),
            "--confirm-raw-lake-write",
        ]
    )
    assert result == 2
    assert capsys.readouterr().err.strip() == "etf_mins_basic_reference_invalid"


def test_raw_observe_cli_is_local_only_and_passes_one_completed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    operation_root = staging_root / "etf_mins" / "operation_id=observe"
    report_path = operation_root / "raw_final_report.json"
    output_dir = operation_root / "raw-observe"
    captured: dict[str, object] = {}

    def fake_observe(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(
            operation_id="observe",
            output_dir=output_dir,
            raw_observation_summary_path=output_dir / "raw_observation_summary.json",
            proposed_policy_path=output_dir / "proposed_policy.json",
            input_manifest_hash="a" * 64,
            observation_summary_hash="b" * 64,
            proposed_policy_hash="c" * 64,
            scanned_file_count=5,
            scanned_row_count=5,
            scanned_byte_count=1_024,
            issue_row_count=0,
            raw_scan_query_count=2,
            analysis_sql_statement_count=12,
            peak_temp_dir_size_bytes=0,
            elapsed_seconds=0.1,
        )

    def prod_resource_must_not_be_created():  # type: ignore[no-untyped-def]
        raise AssertionError("raw-observe must not construct a Prod resource")

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "observe_etf_mins_raw", fake_observe)
    monkeypatch.setattr(cli, "ProdPostgresResource", prod_resource_must_not_be_created)
    assert (
        cli.main(
            [
                "raw-observe",
                "--raw-final-report-path",
                str(report_path),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    assert captured == {
        "lake_root": lake_root,
        "duckdb": captured["duckdb"],
        "raw_bootstrap_report_path": report_path,
        "output_dir": output_dir,
    }
    output = capsys.readouterr().out
    assert "raw_observation_summary.json" in output
    assert '"raw_scan_query_count": 2' in output


def test_raw_decide_cli_is_local_only_and_accepts_only_registered_policy_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    operation_root = staging_root / "etf_mins" / "operation_id=decide"
    observation_path = operation_root / "raw-observe" / "raw_observation_summary.json"
    captured: dict[str, object] = {}

    def fake_decide(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(
            operation_id="decide",
            output_dir=operation_root,
            raw_partition_decision_manifest_path=(
                operation_root / "raw_partition_decision_manifest.parquet"
            ),
            raw_decision_summary_path=operation_root / "raw_decision_summary.json",
            observation_summary_hash="a" * 64,
            approved_policy_version="etf_mins_gap_policy_v1",
            approved_policy_hash="b" * 64,
            raw_partition_decision_manifest_hash="c" * 64,
            raw_decision_summary_hash="d" * 64,
            partition_count=5,
            green_partition_count=5,
            warn_partition_count=0,
            blocked_partition_count=0,
            silver_eligible_partition_count=5,
            analysis_sql_statement_count=12,
            elapsed_seconds=0.1,
        )

    def prod_resource_must_not_be_created():  # type: ignore[no-untyped-def]
        raise AssertionError("raw-decide must not construct a Prod resource")

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "decide_etf_mins_raw", fake_decide)
    monkeypatch.setattr(cli, "ProdPostgresResource", prod_resource_must_not_be_created)
    assert (
        cli.main(
            [
                "raw-decide",
                "--observation-summary-path",
                str(observation_path),
                "--approved-policy-version",
                "etf_mins_gap_policy_v1",
                "--output-dir",
                str(operation_root),
            ]
        )
        == 0
    )
    assert captured == {
        "observation_summary_path": observation_path,
        "approved_policy_version": "etf_mins_gap_policy_v1",
        "output_dir": operation_root,
    }
    output = capsys.readouterr().out
    assert '"approved_policy_version": "etf_mins_gap_policy_v1"' in output
    assert '"partition_count": 5' in output


def test_silver_apply_cli_is_local_only_and_passes_only_frozen_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    operation_root = staging_root / "etf_mins" / "operation_id=silver"
    decision_summary_path = operation_root / "raw_decision_summary.json"
    decision_manifest_path = operation_root / "raw_partition_decision_manifest.parquet"
    checkpoint_path = operation_root / "silver_checkpoint.json"
    final_report_path = operation_root / "physical_final_report.json"
    captured: dict[str, object] = {}

    def fake_apply(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(
            operation_id="silver",
            plan_fingerprint="a" * 64,
            silver_work_manifest_path=operation_root / "silver_work_manifest.parquet",
            silver_work_manifest_hash="b" * 64,
            finalized_silver_manifest_path=(
                operation_root / "finalized_silver_manifest.parquet"
            ),
            finalized_silver_manifest_hash="c" * 64,
            checkpoint_path=checkpoint_path,
            final_report_path=final_report_path,
            raw_file_count=5,
            raw_row_count=100,
            silver_file_count=5,
            silver_row_count=100,
            added_file_count=5,
            reused_file_count=0,
            blocked_partition_count=0,
            warn_partition_count=0,
            report_hash="d" * 64,
        )

    def prod_resource_must_not_be_created():  # type: ignore[no-untyped-def]
        raise AssertionError("silver-apply must not construct a Prod resource")

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "apply_etf_mins_bootstrap_silver", fake_apply)
    monkeypatch.setattr(cli, "ProdPostgresResource", prod_resource_must_not_be_created)
    assert (
        cli.main(
            [
                "silver-apply",
                "--raw-decision-summary-path",
                str(decision_summary_path),
                "--decision-manifest-path",
                str(decision_manifest_path),
                "--checkpoint-path",
                str(checkpoint_path),
                "--final-report-path",
                str(final_report_path),
                "--confirm-silver-lake-write",
            ]
        )
        == 0
    )
    assert captured == {
        "lake_root": lake_root,
        "staging_root": staging_root,
        "duckdb": captured["duckdb"],
        "raw_decision_summary_path": decision_summary_path,
        "decision_manifest_path": decision_manifest_path,
        "checkpoint_path": checkpoint_path,
        "final_report_path": final_report_path,
        "confirm_silver_lake_write": True,
    }
    output = capsys.readouterr().out
    assert '"operation_id": "silver"' in output
    assert str(final_report_path) in output


def test_p9_cli_dry_runs_never_construct_a_prod_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    final_report_path = (
        staging_root / "etf_mins" / "operation_id=p9" / "physical_final_report.json"
    )
    instance = object()
    captured: list[tuple[str, dict[str, object]]] = []

    class _InstanceContext:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return instance

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            del args
            return False

    def fake_partition_plan(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(("partitions", kwargs))
        return SimpleNamespace(to_dict=lambda: {"mode": "dry-run"})

    def fake_event_plan(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(("events", kwargs))
        return SimpleNamespace(to_dict=lambda: {"mode": "dry-run"})

    def prod_resource_must_not_be_created():  # type: ignore[no-untyped-def]
        raise AssertionError("P9 must not construct a Prod resource")

    monkeypatch.setattr(cli, "DEFAULT_LAKE_ROOT", str(lake_root))
    monkeypatch.setattr(cli, "DEFAULT_LAKE_STAGING_ROOT", str(staging_root))
    monkeypatch.setattr(cli, "ProdPostgresResource", prod_resource_must_not_be_created)
    monkeypatch.setattr(cli.dg.DagsterInstance, "get", lambda: _InstanceContext())
    monkeypatch.setattr(
        cli,
        "plan_etf_mins_bootstrap_partitions",
        fake_partition_plan,
    )
    monkeypatch.setattr(cli, "plan_etf_mins_bootstrap_events", fake_event_plan)

    for command in ("partitions", "events"):
        assert cli.main([command, "--final-report-path", str(final_report_path)]) == 0
    assert [name for name, _ in captured] == ["partitions", "events"]
    for _, kwargs in captured:
        assert kwargs == {
            "instance": instance,
            "lake_root": lake_root,
            "staging_root": staging_root,
            "duckdb": kwargs["duckdb"],
            "final_report_path": final_report_path,
        }
    assert capsys.readouterr().out.count('"mode": "dry-run"') == 2
