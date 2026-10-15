from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_weekly_history_cli as cli

from .stock_weekly_capture_test_support import prod_plan


def test_dry_run_never_constructs_exporter_or_creates_roots(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "load_inventory", lambda _: prod_plan())
    monkeypatch.setattr(cli, "bootstrap_header_for_manifest", lambda _: None)
    monkeypatch.setattr(
        cli, "PsqlWeeklyExporter", lambda: pytest.fail("no exporter in dry-run")
    )
    capture, target = tmp_path / "capture", tmp_path / "target"
    assert (
        cli.main(
            [
                "--inventory",
                str(tmp_path / "input.json"),
                "--capture-root",
                str(capture),
                "--target-root",
                str(target),
            ]
        )
        == 0
    )
    assert not capture.exists() and not target.exists()
    assert '"formal_writes": 0' in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        ["--mode", "capture"],
        ["--mode", "build"],
        ["--mode", "promote"],
        ["--apply"],
        ["--year", "2020"],
    ],
)
def test_cli_requires_explicit_stage_and_scope(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(cli, "load_inventory", lambda _: prod_plan())
    monkeypatch.setattr(cli, "bootstrap_header_for_manifest", lambda _: None)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--inventory",
                str(tmp_path / "input.json"),
                "--capture-root",
                str(tmp_path / "capture"),
                "--target-root",
                str(tmp_path / "target"),
                *extra,
            ]
        )


def test_noncanonical_and_overlapping_roots_rejected(tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError

    monkeypatch.setattr(cli, "load_inventory", lambda _: prod_plan())
    monkeypatch.setattr(cli, "bootstrap_header_for_manifest", lambda _: None)
    with pytest.raises(WeeklyCaptureError, match="weekly_root_forbidden"):
        cli.main(
            [
                "--inventory",
                str(tmp_path / "input.json"),
                "--capture-root",
                str(Path("/Users") / "invalid"),
                "--target-root",
                str(tmp_path / "target"),
            ]
        )
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--inventory",
                str(tmp_path / "input.json"),
                "--capture-root",
                str(tmp_path),
                "--target-root",
                str(tmp_path / "target"),
            ]
        )


def test_explicit_frozen_plan_required_and_mismatch_rejected(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError

    plan = prod_plan()
    monkeypatch.setattr(cli, "load_inventory", lambda _: plan)
    frozen = tmp_path / "plan.json"
    frozen.write_text(json.dumps(asdict(plan), default=str))
    args = [
        "--inventory",
        str(tmp_path / "input.json"),
        "--plan",
        str(frozen),
        "--capture-root",
        str(tmp_path / "capture"),
        "--target-root",
        str(tmp_path / "target"),
    ]
    monkeypatch.setattr(
        cli,
        "capture_weekly_history",
        lambda manifest, **kwargs: {"status": "captured", "formal_writes": 0},
    )
    monkeypatch.setattr(cli, "PsqlWeeklyExporter", lambda: object())
    assert cli.main([*args, "--mode", "capture", "--apply"]) == 0
    payload = json.loads(frozen.read_text())
    payload["budget"]["prod_csv_max_bytes"] = 1
    frozen.write_text(json.dumps(payload))
    with pytest.raises(WeeklyCaptureError, match="cli_frozen_plan_mismatch"):
        cli.main(args)
