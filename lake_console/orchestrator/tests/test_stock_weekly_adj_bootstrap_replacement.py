"""B0 replacement in private temporary roots; no Prod, instance or formal Lake."""

import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    build_weekly_partition_candidates,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    capture_file_hash,
)
from orchestrator.defs.bootstrap.stock_weekly_event_files import (
    audit_weekly_event_files,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import (
    promote_weekly_candidates,
    read_audit,
)
from orchestrator.defs.io.stock_weekly_raw import (
    assemble_adjusted_bootstrap_relation,
    load_relation,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    stable_weekly_hash,
    weekly_column_specs,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    ADJUSTED_BOOTSTRAP_MAX_PHASE_ROWS,
    WeeklyAdjProdDeliveryBudget,
)

from .stock_weekly_adj_delivery_test_support import delivery_fixture, source_row
from .stock_weekly_capture_test_support import adjusted_captured

SOURCE = StockWeeklySource.PRIMARY_ADJUSTED
COLS = [n for n, _, _ in weekly_column_specs(SOURCE)]


def frames(*days):
    return [
        pd.DataFrame([source_row(day)], columns=COLS) for day in (days or ("20200228",))
    ]


def build(tmp_path, *days):
    plan, root = adjusted_captured(tmp_path, frames(*days))
    target = tmp_path / "formal"
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=target, year=2020
    )
    return plan, root, target, audit


def test_bootstrap_overwrites_all_values_preserves_dg_only_and_events(tmp_path):
    plan, root, target, audit = build(tmp_path)
    promote_weekly_candidates(audit, apply=True)
    path = partition_path(target, SOURCE, "2020-02-28")
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE old AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        )
        con.execute("INSERT INTO old SELECT '000002.SZ', * EXCLUDE(ts_code) FROM old")
        con.execute(
            "UPDATE old SET close_qfq=999, amount=NULL WHERE ts_code='000001.SZ'"
        )
        con.execute(
            "UPDATE old SET close_qfq=777, amount=NULL WHERE ts_code='000002.SZ'"
        )
        con.execute("COPY old TO ? (FORMAT PARQUET)", [str(path)])
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=target, year=2020
    )
    payload = read_audit(audit)
    assert payload["write_policy"] == "replace_input_keys"
    assert payload["stats"]["replaced_keys"] == payload["stats"]["preserved_keys"] == 1
    assert payload["stats"]["candidate_rows"] == 2
    assert payload["budget"]["max_phase_rows"] == ADJUSTED_BOOTSTRAP_MAX_PHASE_ROWS
    assert WeeklyAdjProdDeliveryBudget().max_phase_rows == 500_000
    promote_weekly_candidates(audit, apply=True)
    with duckdb.connect() as con:
        values = con.execute(
            "SELECT ts_code,CAST(close_qfq AS VARCHAR),amount FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(path)],
        ).fetchall()
    assert values[0][1] == "9.0000" and values[1][1:] == ("777.0000", None)
    entries = audit_weekly_event_files(
        [{"path": str(audit), "sha256": capture_file_hash(audit)}]
    )
    assert len(entries) == 1 and entries[0]["rows"] == 2
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"


def test_zero_unit_b0_uses_inventory_for_full_bootstrap(tmp_path):
    original, _ = delivery_fixture()
    boundary = replace(
        original,
        record_kind="bootstrap_closed",
        rows_received=0,
        rows_unique=0,
        rows_written=0,
        rows_preserved=0,
        header={
            **original.header,
            "bootstrap": True,
            "unit_count": 0,
            "total_payload_bytes": 0,
            "max_input_week": None,
        },
    )
    plan, root = adjusted_captured(tmp_path, frames(), bootstrap_header=boundary)
    assert plan.planned_key_count == 1 and boundary.anchor_partition is None
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=tmp_path / "formal", year=2020
    )
    assert read_audit(audit)["stats"]["candidate_rows"] == 1
    promote_weekly_candidates(audit, apply=True)
    assert (
        len(
            audit_weekly_event_files(
                [{"path": str(audit), "sha256": capture_file_hash(audit)}]
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "change", ["missing", "partial", "wrong_boundary", "receipt", "count"]
)
def test_capture_completion_required_before_candidate_freeze(tmp_path, change):
    plan, root = adjusted_captured(tmp_path, frames())
    marker = next(root.rglob("bootstrap-capture.json"))
    value = json.loads(marker.read_text())
    if change == "missing":
        marker.unlink()
    elif change == "receipt":
        next(root.rglob("receipt.json")).write_text("{}")
    else:
        if change == "partial":
            value["receipts"] = []
        elif change == "count":
            value["source_rows"] += 1
        else:
            value["bootstrap_boundary"]["record_kind"] = "batch_closed"
        marker.write_text(json.dumps(value))
    with pytest.raises(WeeklyCaptureError, match="capture_(required|invalid)"):
        build_weekly_partition_candidates(
            plan, capture_root=root, target_root=tmp_path / "formal", year=2020
        )
    assert not list(root.rglob("audit.json"))
    assert not (tmp_path / "formal").exists()


def test_cross_year_source_rows_and_owned_keys_are_separate(tmp_path):
    plan, root = adjusted_captured(
        tmp_path, frames("20201231", "20210101", "20211231", "20220107")
    )
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=tmp_path / "formal", year=2021
    )
    value = read_audit(audit)
    assert value["stats"]["source_rows"] == 4
    assert value["stats"]["owned_source_rows"] == value["stats"]["candidate_rows"] == 3
    assert [f["week"] for f in value["files"]] == ["2021-01-01", "2021-12-31"]
    promote_weekly_candidates(audit, apply=True)
    assert (
        len(
            audit_weekly_event_files(
                [{"path": str(audit), "sha256": capture_file_hash(audit)}]
            )
        )
        == 2
    )


@pytest.mark.parametrize("change", ["ordinary", "both", "no_policy", "budget", "plan"])
def test_audit_cannot_masquerade_as_other_delivery(tmp_path, change):
    _, _, target, audit = build(tmp_path)
    value = json.loads(audit.read_text())
    if change == "ordinary":
        value["bootstrap_boundary"]["record_kind"] = "batch_closed"
    elif change == "both":
        value["delivery"] = value["bootstrap_boundary"]
    elif change == "no_policy":
        value.pop("write_policy")
    elif change == "plan":
        value["manifest_hash"] = "a" * 64
    else:
        value["budget"]["max_phase_rows"] = ADJUSTED_BOOTSTRAP_MAX_PHASE_ROWS + 1
    value.pop("audit_hash")
    value["audit_hash"] = stable_weekly_hash(value)
    audit.write_text(json.dumps(value))
    with pytest.raises(
        WeeklyCaptureError, match="(identity_mismatch|boundary_required)"
    ):
        promote_weekly_candidates(audit, apply=True)
    assert not target.exists()


@pytest.mark.parametrize("stage", ["before_replace", "after_replace"])
def test_crash_then_replay_recovers_same_bootstrap_audit(tmp_path, stage):
    _, _, _, audit = build(tmp_path)

    def fail(current, week):
        if current == stage:
            raise RuntimeError("exit")

    with pytest.raises(RuntimeError, match="exit"):
        promote_weekly_candidates(audit, apply=True, fault_probe=fail)
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"


def test_cancel_after_first_file_preserves_it_on_resume(tmp_path):
    _, _, _, audit = build(tmp_path, "20200228", "20200306")
    completed = []
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        promote_weekly_candidates(
            audit, apply=True, cancel=lambda: bool(completed), progress=completed.append
        )
    first = Path(read_audit(audit)["files"][0]["target"])
    digest = capture_file_hash(first)
    promote_weekly_candidates(audit, apply=True)
    assert capture_file_hash(first) == digest


def test_conflicting_source_keys_and_row_budget_rejected(tmp_path):
    _, _, _, audit = build(tmp_path)
    path = Path(read_audit(audit)["files"][0]["candidate"])
    with duckdb.connect() as con:
        load_relation(con, "weekly_input", [path], SOURCE)
        load_relation(con, "weekly_existing", [path], SOURCE)
        budget = WeeklyAdjProdDeliveryBudget().weekly_budget()
        with pytest.raises(WeeklyCaptureError, match="row_budget"):
            assemble_adjusted_bootstrap_relation(
                con, year=2020, budget=replace(budget, max_phase_rows=1)
            )
        con.execute("INSERT INTO weekly_input SELECT * FROM weekly_input")
        with pytest.raises(WeeklyCaptureError, match="duplicate_key"):
            assemble_adjusted_bootstrap_relation(con, year=2020, budget=budget)
