"""Offline tests of the approved history scope, interrupted execution and physical audit."""

import json
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_monthly_files import (
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_monthly_history import (
    audit_monthly_history,
    execute_monthly_history,
    monthly_history_preflight,
)
from orchestrator.defs.bootstrap.stock_monthly_history_cli import main
from orchestrator.defs.bootstrap.stock_monthly_history_plan import (
    freeze_monthly_history_plan,
    load_monthly_history_plan,
    monthly_history_plan_payload,
)
from orchestrator.defs.paths import raw_stock_monthly_path
from orchestrator.defs.run_contracts.stock_monthly import monthly_contract_hash
from tests.test_stock_monthly_bootstrap import FixtureExporter, fixture_rows


def fixture(tmp_path, source="primary_unadjusted"):
    lake, stage = tmp_path / "lake", tmp_path / "stage"
    lake.mkdir(); stage.mkdir()
    records = [
        {"section": "snapshot", "readonly": "on", "snapshot": "fixture:1", "audited_at": "2026-10-05"},
        {"section": "year", "table": "stk_period_bar" + ("_adj" if source == "primary_adjusted" else ""),
         "year": 2020, "rows": 6, "codes": ["000001.SZ", "600000.SH"]},
    ]
    records.extend({"section": "date", "table": records[1]["table"], "date": day, "rows": 2} for day in ("2020-01-31", "2020-02-28", "2020-02-29"))
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text("".join(json.dumps(r) + "\n" for r in records))
    plan = freeze_monthly_history_plan(inventory, source, "2020-01", "2020-02")
    return plan, lake, stage, FixtureExporter(fixture_rows(source))


@pytest.mark.parametrize("source", ["primary_unadjusted", "primary_adjusted"])
def test_complete_history_and_replay_reconcile_every_field(tmp_path, source):
    plan, lake, stage, exporter = fixture(tmp_path, source)
    before = set(stage.rglob("*"))
    preflight = monthly_history_preflight(plan, lake, stage)
    assert set(stage.rglob("*")) == before
    assert preflight["counts"] == {"source_rows": 6, "excluded_rows": 2, "accepted_rows": 4, "units": 1, "years": 1, "files": 2}
    result = execute_monthly_history(plan, preflight, exporter=exporter)
    assert (result["rows"], result["source_rows"], result["excluded_rows"], result["year_scans"]) == (4, 6, 2, 1)
    assert result["sql_calls"] == 12  # two file schema probes plus ten annual SQL calls
    assert exporter.calls == 1
    assert all(e["delivery_method"] == "prod_month_bootstrap" for e in result["entries"])
    again = execute_monthly_history(plan, preflight, exporter=exporter)
    assert exporter.calls == 1
    assert again["entries"] == result["entries"]
    assert audit_monthly_history(plan, lake, stage)["entries"] == result["entries"]


def test_cancel_after_receipt_resumes_without_source(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    preflight = monthly_history_preflight(plan, lake, stage)
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event["phase"] == "capture_committed":
            cancelled = True

    with pytest.raises(ValueError, match="monthly_cancelled"):
        execute_monthly_history(plan, preflight, exporter=exporter, progress=progress, cancel=lambda: cancelled)
    assert exporter.calls == 1
    assert not list(lake.rglob("*.parquet"))
    assert len(list(stage.rglob("receipt.json"))) == 1
    assert execute_monthly_history(plan, preflight, exporter=exporter)["rows"] == 4
    assert exporter.calls == 1


def test_exit_after_promotion_keeps_audit_and_resumes(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    preflight = monthly_history_preflight(plan, lake, stage)

    def progress(event):
        if event["phase"] == "history_year_committed":
            raise RuntimeError("simulated exit")

    with pytest.raises(RuntimeError, match="simulated exit"):
        execute_monthly_history(plan, preflight, exporter=exporter, progress=progress)
    assert len(list(lake.rglob("*.parquet"))) == 2
    assert len(list(stage.rglob("history_execution.json"))) == 1
    assert execute_monthly_history(plan, preflight, exporter=exporter)["files"] == 2
    assert exporter.calls == 1


@pytest.mark.parametrize("field", ["source", "accepted_rows", "units", "plan_hash"])
def test_serialized_plan_does_not_override_physical_inventory(tmp_path, field):
    plan, _, _, _ = fixture(tmp_path)
    payload = monthly_history_plan_payload(plan)
    payload["plan"][field] = "wrong"
    path = tmp_path / "plan.json"
    write_monthly_json(path, payload, 1024**2)
    with pytest.raises((ValueError, TypeError)):
        load_monthly_history_plan(path)


def test_scope_cannot_be_shrunk_using_whole_year_inventory(tmp_path):
    plan, _, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="outside_scope"):
        freeze_monthly_history_plan(plan.inventory_ref, plan.source, "2020-02", "2020-02")


@pytest.mark.parametrize("kind", ["readonly", "count", "date_duplicate", "duplicate_year"])
def test_bad_inventory_is_not_a_plan(tmp_path, kind):
    plan, _, _, _ = fixture(tmp_path)
    path = Path(plan.inventory_ref)
    rows = [json.loads(r) for r in path.read_text().splitlines()]
    if kind == "readonly": rows[0]["readonly"] = "off"
    if kind == "count": rows[1]["rows"] = 7
    if kind == "date_duplicate": rows.append(rows[2])
    if kind == "duplicate_year": rows.append(rows[1])
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(ValueError):
        freeze_monthly_history_plan(path, plan.source, "2020-01", "2020-02")


def test_target_drift_rejects_before_source_request(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    preflight = monthly_history_preflight(plan, lake, stage)
    target = raw_stock_monthly_path(lake, plan.source, "2020-01")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unapproved target")
    with pytest.raises(ValueError, match="target_changed"):
        execute_monthly_history(plan, preflight, exporter=exporter)
    assert exporter.calls == 0
    assert target.read_bytes() == b"unapproved target"


def test_baseline_deletion_is_drift_not_an_owned_target(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    target = raw_stock_monthly_path(lake, plan.source, "2020-01")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"baseline")
    preflight = monthly_history_preflight(plan, lake, stage)
    moved = tmp_path / "moved_baseline"
    target.rename(moved)  # reversible fixture operation, no business deletion
    with pytest.raises(ValueError, match="target_changed"):
        execute_monthly_history(plan, preflight, exporter=exporter)
    assert exporter.calls == 0


def test_target_corruption_cannot_be_marked_green(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    execute_monthly_history(plan, monthly_history_preflight(plan, lake, stage), exporter=exporter)
    target = raw_stock_monthly_path(lake, plan.source, "2020-01")
    target.write_bytes(b"corrupted")
    with pytest.raises((ValueError, duckdb.Error)):
        audit_monthly_history(plan, lake, stage)


def test_preflight_scope_and_hash_fail_closed(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    preflight = monthly_history_preflight(plan, lake, stage)
    preflight["files"].pop()
    body = {k: v for k, v in preflight.items() if k != "preflight_hash"}
    preflight["preflight_hash"] = monthly_contract_hash(body)
    with pytest.raises(ValueError, match="scope_changed"):
        execute_monthly_history(plan, preflight, exporter=exporter)
    assert exporter.calls == 0
    assert not list(stage.rglob("*"))


def test_cli_defaults_to_readonly_and_apply_requires_external_hash(tmp_path):
    plan, lake, stage, _ = fixture(tmp_path)
    frozen = tmp_path / "plan.json"
    write_monthly_json(frozen, monthly_history_plan_payload(plan), 1024**2)
    output = tmp_path / "preflight.json"
    args = ["--plan", str(frozen), "--lake-root", str(lake), "--staging-root", str(stage), "--output", str(output)]
    assert main(args) == 0
    assert not list(stage.rglob("*"))
    with pytest.raises(SystemExit): main(["apply", *args])
    with pytest.raises(ValueError, match="preflight_file_changed"):
        main(["apply", *args, "--output", str(tmp_path / "result.json"), "--preflight", str(output), "--preflight-sha256", "0" * 64])
    assert not list(stage.rglob("*"))


def test_cli_never_writes_control_into_lake(tmp_path):
    plan, lake, _, _ = fixture(tmp_path)
    with pytest.raises(SystemExit):
        main(["freeze", "--inventory", plan.inventory_ref, "--source", plan.source.value,
              "--first-month", "2020-01", "--last-month", "2020-02", "--lake-root", str(lake), "--output", str(lake / "control.json")])


def test_wrong_file_placement_cannot_pass_aggregate_audit(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    execute_monthly_history(plan, monthly_history_preflight(plan, lake, stage), exporter=exporter)
    first = raw_stock_monthly_path(lake, plan.source, "2020-01")
    second = raw_stock_monthly_path(lake, plan.source, "2020-02")
    saved = tmp_path / "swap.parquet"
    first.rename(saved); second.rename(first); saved.rename(second)
    with pytest.raises(ValueError, match="placement_invalid"):
        audit_monthly_history(plan, lake, stage)


def test_mutated_receipt_cannot_pass_readonly_audit(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    execute_monthly_history(plan, monthly_history_preflight(plan, lake, stage), exporter=exporter)
    receipt = next(stage.rglob("receipt.json"))
    receipt.write_text(receipt.read_text() + " ")
    with pytest.raises(ValueError, match="receipt_changed"):
        audit_monthly_history(plan, lake, stage)


def test_cli_apply_with_frozen_scope_and_hash_in_isolation(tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap import stock_monthly_history
    from orchestrator.defs.bootstrap.stock_monthly_files import monthly_file_hash
    plan, lake, stage, exporter = fixture(tmp_path)
    monkeypatch.setattr(stock_monthly_history, "PsqlMonthlyExporter", lambda: exporter)
    frozen, preflight, output = (tmp_path / n for n in ("plan.json", "preflight.json", "audit.json"))
    write_monthly_json(frozen, monthly_history_plan_payload(plan), 1024**2)
    write_monthly_json(preflight, monthly_history_preflight(plan, lake, stage), 1024**2)
    args = ["apply", "--plan", str(frozen), "--preflight", str(preflight), "--preflight-sha256", monthly_file_hash(preflight), "--lake-root", str(lake), "--staging-root", str(stage), "--output", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text())["rows"] == 4
    assert main(args) == 0
    assert exporter.calls == 1


def test_orphan_inventory_date_is_not_silently_dropped(tmp_path):
    plan, _, _, _ = fixture(tmp_path)
    path = Path(plan.inventory_ref)
    records = [json.loads(r) for r in path.read_text().splitlines()]
    records.append({"section": "date", "table": "stk_period_bar", "date": "2021-01-31", "rows": 1})
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    with pytest.raises(ValueError, match="unaccounted_date"):
        freeze_monthly_history_plan(path, plan.source, "2020-01", "2020-02")


def test_excluded_version_evidence_must_survive_bootstrap(tmp_path):
    plan, lake, stage, exporter = fixture(tmp_path)
    execute_monthly_history(plan, monthly_history_preflight(plan, lake, stage), exporter=exporter)
    exclusion = next(stage.rglob("excluded_month_version.parquet"))
    exclusion.write_bytes(b"bad exclusion ledger")
    with pytest.raises(ValueError, match="exclusion_changed"):
        audit_monthly_history(plan, lake, stage)
