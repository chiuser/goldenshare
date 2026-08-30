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


def test_cli_exposes_only_the_two_authorized_stages_and_requires_write_flag() -> None:
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
    for future_stage in (
        "raw-observe",
        "raw-decide",
        "silver-apply",
        "partitions",
        "events",
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([future_stage])


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
