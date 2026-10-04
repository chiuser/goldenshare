from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_weekly_history_cli as cli

from .stock_weekly_capture_test_support import prod_plan


def test_dry_run_never_constructs_exporter_or_creates_roots(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "load_inventory", lambda _: prod_plan())
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


def alternate_inventory(tmp_path):
    import csv
    import json

    from orchestrator.defs.bootstrap.stock_weekly_capture import capture_file_hash

    proof = tmp_path / "proof.csv"
    proof.write_text("source\nobserved\n")
    candidates = tmp_path / "candidates.csv"
    with candidates.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ts_code",
                "week_key",
                "availability",
                "source_evidence_ref",
                "source_evidence_hash",
            ]
        )
        w.writerow(
            [
                "000005.SZ",
                "2020-02-28",
                "source_available",
                str(proof),
                capture_file_hash(proof),
            ]
        )
        w.writerow(["000005.SZ", "2020-03-06", "source_unchecked", "", ""])
    expected = tmp_path / "keys.csv"
    expected.write_text("ts_code,week_key\n000005.SZ,2020-02-28\n")
    payload = {
        "kind": "weekly_history_inventory",
        "version": 1,
        "anchor_start": "2020-01-03",
        "anchor_end": "2020-12-25",
        "excluded_week_keys": [],
        "candidates": {
            "path": str(candidates),
            "sha256": capture_file_hash(candidates),
        },
        "expected": {"path": str(expected), "sha256": capture_file_hash(expected)},
    }
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(payload))
    return inventory, payload


def test_alternate_loader_only_plans_available_and_dry_run_requires_no_token(
    tmp_path, monkeypatch
):
    inventory, _ = alternate_inventory(tmp_path)
    plan = cli.load_inventory(inventory)
    assert len(plan.units) == 1 and plan.planned_key_count == 1
    assert plan.skipped_key_count == 1
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(
        cli, "WeeklySdkWorker", lambda *_: pytest.fail("no source in dry run")
    )
    assert (
        cli.main(
            [
                "--inventory",
                str(inventory),
                "--capture-root",
                str(tmp_path / "capture"),
                "--target-root",
                str(tmp_path / "target"),
            ]
        )
        == 0
    )
    assert not (tmp_path / "capture").exists()


@pytest.mark.parametrize(
    "tamper",
    [
        "candidate_hash",
        "expected_hash",
        "expected_set",
        "proof_hash",
        "duplicate",
        "availability",
    ],
)
def test_alternate_inventory_rejects_changed_or_invalid_evidence(tmp_path, tamper):
    import json

    from orchestrator.defs.bootstrap.stock_weekly_capture import (
        WeeklyCaptureError,
        capture_file_hash,
    )

    inventory, payload = alternate_inventory(tmp_path)
    if tamper in ("candidate_hash", "expected_hash"):
        payload["candidates" if tamper == "candidate_hash" else "expected"][
            "sha256"
        ] = "a" * 64
    elif tamper == "proof_hash":
        (tmp_path / "proof.csv").write_text("changed")
    elif tamper == "expected_set":
        (tmp_path / "keys.csv").write_text("ts_code,week_key\n000005.SZ,2020-03-06\n")
        payload["expected"]["sha256"] = capture_file_hash(tmp_path / "keys.csv")
    else:
        p = tmp_path / "candidates.csv"
        if tamper == "duplicate":
            p.write_text(p.read_text() + p.read_text().splitlines()[1] + "\n")
        else:
            p.write_text(p.read_text().replace("source_available", ""))
        payload["candidates"]["sha256"] = capture_file_hash(p)
    inventory.write_text(json.dumps(payload))
    with pytest.raises((WeeklyCaptureError, ValueError)):
        cli.load_inventory(inventory)


def test_alternate_capture_selects_sdk_and_anchor_year(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    inventory, _ = alternate_inventory(tmp_path)
    plan = cli.load_inventory(inventory)
    frozen = tmp_path / "plan.json"
    frozen.write_text(json.dumps(asdict(plan), default=str))
    args = [
        "--inventory",
        str(inventory),
        "--plan",
        str(frozen),
        "--capture-root",
        str(tmp_path / "capture"),
        "--target-root",
        str(tmp_path / "target"),
    ]
    monkeypatch.setattr(
        cli, "PsqlWeeklyExporter", lambda: pytest.fail("alternate must not access Prod")
    )
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError

    with pytest.raises(WeeklyCaptureError, match="weekly_token_required"):
        cli.main([*args, "--mode", "capture", "--apply"])
    sentinel = object()
    monkeypatch.setenv("TUSHARE_TOKEN", "offline-placeholder")
    monkeypatch.setattr(cli, "WeeklySdkWorker", lambda token: sentinel)

    def capture(manifest, **kwargs):
        assert kwargs["worker"] is sentinel and kwargs["prod_exporter"] is None
        return {"status": "captured"}

    monkeypatch.setattr(cli, "capture_weekly_history", capture)
    assert cli.main([*args, "--mode", "capture", "--apply"]) == 0
    monkeypatch.setattr(
        cli, "build_weekly_partition_candidates", lambda *a, **k: {"year": k["year"]}
    )
    assert cli.main([*args, "--mode", "build", "--year", "2020", "--apply"]) == 0
    with pytest.raises(SystemExit):
        cli.main([*args, "--mode", "build", "--year", "2021", "--apply"])


def test_confirmed_empty_candidate_evidence_must_still_match(tmp_path):
    import json

    from orchestrator.defs.bootstrap.stock_weekly_capture import (
        WeeklyCaptureError,
        capture_file_hash,
    )

    inventory, payload = alternate_inventory(tmp_path)
    candidates = tmp_path / "candidates.csv"
    rows = candidates.read_text().splitlines()
    rows[2] = (
        rows[1]
        .replace("2020-02-28", "2020-03-06")
        .replace("source_available", "source_empty_confirmed")
    )
    candidates.write_text("\n".join(rows) + "\n")
    payload["candidates"]["sha256"] = capture_file_hash(candidates)
    inventory.write_text(json.dumps(payload))
    plan = cli.load_inventory(inventory)
    assert plan.planned_key_count == plan.skipped_key_count == 1
    rows[2] = rows[2].rsplit(",", 1)[0] + "," + "a" * 64
    candidates.write_text("\n".join(rows) + "\n")
    payload["candidates"]["sha256"] = capture_file_hash(candidates)
    inventory.write_text(json.dumps(payload))
    with pytest.raises(WeeklyCaptureError, match="source_evidence_hash_mismatch"):
        cli.load_inventory(inventory)
