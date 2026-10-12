"""Offline B0 capture tests: only temporary files, no instance, DB or network."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from threading import Event

import pandas as pd
import pytest

from orchestrator.defs.bootstrap import stock_weekly_history_cli as cli
from orchestrator.defs.bootstrap.stock_weekly_adj_bootstrap import (
    AdjustedWeeklyBootstrapGuard,
    validate_bootstrap_inventory,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    capture_file_hash,
)
from orchestrator.defs.bootstrap.stock_weekly_history import capture_weekly_history
from orchestrator.defs.prod_db.stock_weekly_adj_delivery import (
    PsqlWeeklyAdjDeliveryReader,
    build_bootstrap_boundary_sql,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
)
from orchestrator.defs.run_contracts.stock_weekly_adj_delivery import (
    WeeklyAdjProdDeliveryBudget,
)

from .stock_weekly_adj_delivery_test_support import delivery_fixture, source_row
from .stock_weekly_capture_test_support import FakePsqlExporter, prod_plan

SOURCE = StockWeeklySource.PRIMARY_ADJUSTED


def boundary():
    header, _ = delivery_fixture()
    return replace(
        header,
        record_kind="bootstrap_closed",
        header={**header.header, "bootstrap": True},
    )


def inventory(tmp_path, *, count=1):
    proof = tmp_path / "inventory.csv"
    proof.write_text(
        f"source,year,ts_code,source_rows\n{SOURCE.value},2020,000001.SZ,{count}\n"
    )
    payload = {
        "version": 1,
        "kind": "prod_weekly_inventory",
        "source": SOURCE.value,
        "inventories": [{"year": 2020, "codes": ["000001.SZ"], "source_rows": count}],
        "bootstrap_boundary": asdict(boundary()),
        "snapshot": [{"readonly": "on", "isolation": "repeatable read"}],
        "empty_years": [],
        "date_window": ["2020-01-01", "2021-01-01"],
        "input_inventory": {"path": str(proof), "sha256": capture_file_hash(proof)},
    }
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload))
    return path, cli.load_inventory(path)


class OfflineBoundaryReader(PsqlWeeklyAdjDeliveryReader):
    def __init__(self, *, fail_at=None):
        super().__init__()
        self.calls = []
        self.fail_at = fail_at
        self.inventory_rows = 1
        self.value = {
            "latest_revision": boundary().revision,
            "boundary": asdict(boundary()),
        }

    def _query(self, sql, byte_limit, *, cancel, progress, record_csv=False):
        assert not cancel()
        self.calls.append((sql, byte_limit))
        value = deepcopy(self.value)
        if "AS inventory_rows" in sql:
            value["inventory_rows"] = self.inventory_rows
        if len(self.calls) == self.fail_at:
            value["latest_revision"] += 1
        return value


def exporter():
    columns = [n for n, _, _ in weekly_column_specs(SOURCE)]
    return FakePsqlExporter(pd.DataFrame([source_row("20200228")], columns=columns))


def test_boundary_query_includes_all_business_revisions_and_only_explicit_control():
    sql = build_bootstrap_boundary_sql(boundary(), WeeklyAdjProdDeliveryBudget())
    latest = sql.split("AS latest_revision")[0]
    assert "ORDER BY revision DESC LIMIT 1" in latest
    assert "record_kind" not in latest
    assert "READ ONLY" in sql and sql.endswith("ROLLBACK;\n")
    assert "intent->'bootstrap'='true'::jsonb" in sql
    assert "payload->'header' AS header" in sql
    assert "SELECT *" not in sql and "raw_tushare" not in sql


@pytest.mark.parametrize(
    "change", ["revision", "missing", "cutoff", "digest", "unknown"]
)
def test_wrong_or_changed_boundary_rejected(change):
    reader = OfflineBoundaryReader()
    if change == "revision":
        reader.value["latest_revision"] += 1
    elif change == "missing":
        reader.value["boundary"] = None
    elif change == "cutoff":
        reader.value["boundary"]["cutoff_week"] = "2026-10-02"
    elif change == "digest":
        reader.value["boundary"]["payload_digest"] = "f" * 64
    else:
        reader.value["extra"] = True
    with pytest.raises(WeeklyCaptureError, match="source_changed"):
        reader.assert_bootstrap_current(boundary())
    assert reader.calls[0][1] == 4096


@pytest.mark.parametrize(
    "change", ["missing", "ordinary", "false", "version", "wrong_source"]
)
def test_inventory_requires_actual_bootstrap_header(change):
    payload = {"source": SOURCE.value, "bootstrap_boundary": asdict(boundary())}
    if change == "missing":
        payload.pop("bootstrap_boundary")
    elif change == "ordinary":
        payload["bootstrap_boundary"]["record_kind"] = "batch_closed"
    elif change == "false":
        payload["bootstrap_boundary"]["header"]["bootstrap"] = False
    elif change == "version":
        payload["bootstrap_boundary"]["contract_version"] = 2
    else:
        payload["source"] = StockWeeklySource.PRIMARY_UNADJUSTED.value
    with pytest.raises(WeeklyCaptureError):
        validate_bootstrap_inventory(payload)


def test_capture_seals_all_receipts_and_reuses_without_refetch(tmp_path):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader()
    guard = AdjustedWeeklyBootstrapGuard(plan, reader=reader)
    first = exporter()
    result = capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=first, bootstrap_guard=guard
    )
    assert result["source_rows"] == 1 and result["formal_writes"] == 0
    assert len(reader.calls) == 4 and first.calls == 1
    path = tmp_path / "stock_weekly_raw" / plan.plan_hash / "bootstrap-capture.json"
    sealed = path.read_bytes()
    value = json.loads(sealed)
    assert value["bootstrap_boundary"] == asdict(boundary())
    assert value["plan_hash"] == plan.plan_hash
    assert value["source_rows"] == 1 and len(value["receipts"]) == 1
    receipt_path = next(tmp_path.rglob("receipt.json"))
    assert value["receipts"][0]["sha256"] == capture_file_hash(receipt_path)
    repeated = exporter()
    assert (
        capture_weekly_history(
            plan, capture_root=tmp_path, prod_exporter=repeated, bootstrap_guard=guard
        )
        == result
    )
    assert repeated.calls == 0 and path.read_bytes() == sealed
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_change_at_any_capture_boundary_never_seals(tmp_path, fail_at):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader(fail_at=fail_at)
    source = exporter()
    with pytest.raises(WeeklyCaptureError, match="source_changed"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=source,
            bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
        )
    assert source.calls == (0 if fail_at <= 2 else 1)
    assert not list(tmp_path.rglob("bootstrap-capture.json"))
    reader.fail_at = None
    reader.value["latest_revision"] += 1
    resumed = exporter()
    with pytest.raises(WeeklyCaptureError, match="source_changed"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=resumed,
            bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
        )
    assert resumed.calls == 0


def test_cancel_after_unit_resumes_same_b0_without_export(tmp_path):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader()
    guard = AdjustedWeeklyBootstrapGuard(plan, reader=reader)
    canceled = Event()

    def progress(value):
        if value.get("completed_units") == 1:
            canceled.set()

    with pytest.raises(WeeklyCaptureError, match="canceled"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=exporter(),
            bootstrap_guard=guard,
            cancel=canceled.is_set,
            progress=progress,
        )
    assert list(tmp_path.rglob("receipt.json"))
    assert not list(tmp_path.rglob("bootstrap-capture.json"))
    resumed = exporter()
    capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=resumed, bootstrap_guard=guard
    )
    assert resumed.calls == 0
    assert len(list(tmp_path.rglob("bootstrap-capture.json"))) == 1


def test_frozen_inventory_count_mismatch_never_seals(tmp_path):
    _, plan = inventory(tmp_path, count=2)
    reader = OfflineBoundaryReader()
    reader.inventory_rows = 2
    with pytest.raises(WeeklyCaptureError, match="capture_incomplete"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=exporter(),
            bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
        )
    assert not list(tmp_path.rglob("bootstrap-capture.json"))


def test_guard_missing_or_foreign_stops_before_creating_capture(tmp_path):
    _, plan = inventory(tmp_path)
    with pytest.raises(WeeklyCaptureError, match="boundary_required"):
        capture_weekly_history(
            plan, capture_root=tmp_path / "stage", prod_exporter=exporter()
        )
    assert not (tmp_path / "stage").exists()
    with pytest.raises(WeeklyCaptureError, match="inventory_changed"):
        AdjustedWeeklyBootstrapGuard(
            plan, reader=OfflineBoundaryReader()
        ).validate_manifest(replace(plan, plan_hash="c" * 64))
    unadjusted = prod_plan()
    assert validate_bootstrap_inventory({"source": unadjusted.source.value}) is None


@pytest.mark.parametrize("mode", ["build", "promote"])
def test_cli_cannot_fall_into_old_adjusted_write_policy(tmp_path, mode):
    path, _ = inventory(tmp_path)
    with pytest.raises(WeeklyCaptureError, match="replacement_stage_required"):
        cli.main(
            [
                "--inventory",
                str(path),
                "--capture-root",
                str(tmp_path / "stage"),
                "--target-root",
                str(tmp_path / "lake"),
                "--mode",
                mode,
            ]
        )
    assert not (tmp_path / "stage").exists() and not (tmp_path / "lake").exists()


def test_adjusted_cli_dry_run_never_constructs_reader_or_exporter(
    tmp_path, monkeypatch, capsys
):
    path, _ = inventory(tmp_path)
    monkeypatch.setattr(
        cli, "PsqlWeeklyExporter", lambda: pytest.fail("dry-run source access")
    )
    monkeypatch.setattr(
        cli,
        "AdjustedWeeklyBootstrapGuard",
        lambda _: pytest.fail("dry-run guard access"),
    )
    assert (
        cli.main(
            [
                "--inventory",
                str(path),
                "--capture-root",
                str(tmp_path / "stage"),
                "--target-root",
                str(tmp_path / "lake"),
            ]
        )
        == 0
    )
    assert '"instance_writes": 0' in capsys.readouterr().out
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("inventory_rows", [0, 2, True, None])
def test_inventory_omission_rejected_before_export(tmp_path, inventory_rows):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader()
    reader.inventory_rows = inventory_rows
    source = exporter()
    with pytest.raises(WeeklyCaptureError, match="inventory_count_mismatch"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=source,
            bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
        )
    assert source.calls == 0
    assert len(reader.calls) == 1
    assert not list(tmp_path.rglob("receipt.json"))


def test_full_inventory_count_only_in_first_control_query(tmp_path):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader()
    capture_weekly_history(
        plan,
        capture_root=tmp_path,
        prod_exporter=exporter(),
        bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
    )
    assert sum("raw_tushare.stk_period_bar_adj" in sql for sql, _ in reader.calls) == 1


def test_precanceled_capture_never_queries_prod(tmp_path):
    _, plan = inventory(tmp_path)
    reader = OfflineBoundaryReader()
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        capture_weekly_history(
            plan,
            capture_root=tmp_path,
            prod_exporter=exporter(),
            bootstrap_guard=AdjustedWeeklyBootstrapGuard(plan, reader=reader),
            cancel=lambda: True,
        )
    assert not reader.calls
    assert not list(tmp_path.rglob("bootstrap-capture.json"))


def test_changed_receipt_never_resumes_or_rewrites_complete_seal(tmp_path):
    _, plan = inventory(tmp_path)
    guard = AdjustedWeeklyBootstrapGuard(plan, reader=OfflineBoundaryReader())
    capture_weekly_history(
        plan, capture_root=tmp_path, prod_exporter=exporter(), bootstrap_guard=guard
    )
    marker = next(tmp_path.rglob("bootstrap-capture.json"))
    baseline = marker.read_bytes()
    receipt_path = next(tmp_path.rglob("receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    receipt["source_rows"] = 2
    receipt_path.write_text(json.dumps(receipt))
    source = exporter()
    with pytest.raises(WeeklyCaptureError, match="capture_count_mismatch"):
        capture_weekly_history(
            plan, capture_root=tmp_path, prod_exporter=source, bootstrap_guard=guard
        )
    assert source.calls == 0 and marker.read_bytes() == baseline


def test_modified_unit_cannot_keep_frozen_inventory_identity(tmp_path):
    _, plan = inventory(tmp_path)
    changed = replace(
        plan, units=(replace(plan.units[0], sorted_codes=("000002.SZ",)),)
    )
    with pytest.raises(WeeklyCaptureError, match="inventory_invalid"):
        AdjustedWeeklyBootstrapGuard(changed, reader=OfflineBoundaryReader())
