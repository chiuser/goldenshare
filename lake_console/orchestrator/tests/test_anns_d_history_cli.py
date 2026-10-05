"""Explicit stages and report identity gates do not open unauthorized resources."""

import tempfile
from pathlib import Path

import pytest

from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap.anns_d_history_cli import (
    announcement_history_parser,
    execute_announcement_history_cli,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    save_announcement_history_report,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_history_plan import month_plan

archive = _archive_fixture


@pytest.mark.parametrize(
    "stage,extra",
    [
        ("capture", []),
        ("build", []),
        ("promote", ["--fingerprint", "abc"]),
        ("audit", ["--formal"]),
        ("status", ["--formal"]),
    ],
)
def test_stage_invalid_arguments_fail_before_any_resource(
    archive, monkeypatch, stage, extra
):
    import orchestrator.defs.bootstrap.anns_d_history_cli as module

    monkeypatch.setattr(
        module,
        "ProdPostgresResource",
        lambda: pytest.fail("invalid arguments opened source"),
    )
    monkeypatch.setattr(
        module,
        "run_announcement_history_stage",
        lambda *a, **k: pytest.fail("invalid stage touched files"),
    )
    args = announcement_history_parser().parse_args(
        [stage, "--plan", "/private/tmp/not-a-plan.json", *extra]
    )
    with pytest.raises(AnnouncementError):
        execute_announcement_history_cli(args, archive.control)


def test_status_zero_writes_no_source(archive, monkeypatch):
    import orchestrator.defs.bootstrap.anns_d_history_cli as module
    from orchestrator.defs.bootstrap.anns_d_history_plan import (
        validate_announcement_history_plan,
    )

    plan = month_plan(archive)
    monkeypatch.setattr(
        module,
        "validate_announcement_history_plan",
        lambda p: validate_announcement_history_plan(
            p, roots=(archive.root, archive.staging)
        ),
    )
    monkeypatch.setattr(
        module, "ProdPostgresResource", lambda: pytest.fail("status opened source")
    )
    before = list(archive.staging.rglob("*"))
    with tempfile.TemporaryDirectory(
        dir="/private/tmp", prefix="anns-cli-test-"
    ) as directory:
        path = Path(directory) / "plan.json"
        save_announcement_history_report(path, plan)
        args = announcement_history_parser().parse_args(["status", "--plan", str(path)])
        result = execute_announcement_history_cli(args, archive.control)
    assert result["months"] == [
        {"month": "2023-06-01", "phase": "planned", "source_rows": 0}
    ]
    assert list(archive.staging.rglob("*")) == before


def test_parser_default_plan_and_no_generic_sql_table_or_root():
    assert announcement_history_parser().parse_args([]).stage == "plan"
    for option in ("--root", "--table", "--sql", "--apply", "report-events"):
        with pytest.raises(SystemExit):
            announcement_history_parser().parse_args([option])


def test_wrong_plan_fingerprint_does_not_open_store_or_source(archive, monkeypatch):
    import orchestrator.defs.bootstrap.anns_d_history_cli as module

    plan = month_plan(archive)
    monkeypatch.setattr(
        module, "ProdPostgresResource", lambda: pytest.fail("wrong plan opened source")
    )
    with tempfile.TemporaryDirectory(
        dir="/private/tmp", prefix="anns-cli-test-"
    ) as directory:
        path = Path(directory) / "plan.json"
        save_announcement_history_report(path, plan)
        args = announcement_history_parser().parse_args(
            ["capture", "--plan", str(path), "--fingerprint", "wrong"]
        )
        with pytest.raises(AnnouncementError, match="plan_identity"):
            execute_announcement_history_cli(args, archive.control)


def test_plan_checks_external_volume_before_opening_prod(archive, monkeypatch):
    import orchestrator.defs.bootstrap.anns_d_history_cli as module

    def missing(*args):
        raise AnnouncementError("announcement_volume_missing")

    monkeypatch.setattr(module, "announcement_bootstrap_volume_gate", missing)
    monkeypatch.setattr(
        module,
        "ProdPostgresResource",
        lambda: pytest.fail("volume failure opened Prod"),
    )
    args = announcement_history_parser().parse_args(
        [
            "--start-date",
            "2023-06-01",
            "--end-date",
            "2023-06-30",
            "--run-id",
            "history",
            "--report",
            "/private/tmp/anns-unused-volume-plan.json",
        ]
    )
    with pytest.raises(AnnouncementError, match="volume_missing"):
        execute_announcement_history_cli(args, archive.control)
