import json
from dataclasses import asdict, replace

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    build_weekly_partition_candidates,
    verified_empty_inventory_intervals,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
    capture_file_hash,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
)
from orchestrator.defs.stock_weekly_planner import freeze_prod_weekly_plan

from .stock_weekly_capture_test_support import prod_frame


def frozen(tmp_path):
    inventories = (
        ProdYearInventory(2009, (), 0),
        ProdYearInventory(2010, ("000005.SZ",), 1),
        ProdYearInventory(2011, (), 0),
    )
    raw = tmp_path / "inventory.csv"
    raw.write_text(
        "source,year,ts_code,source_rows\nprimary_unadjusted,2010,000005.SZ,1\n"
    )
    proof = tmp_path / "inventory.json"
    proof.write_text(
        json.dumps(
            {
                "kind": "prod_weekly_inventory",
                "version": 1,
                "source": StockWeeklySource.PRIMARY_UNADJUSTED.value,
                "inventories": [asdict(i) for i in inventories],
                "date_window": ["2009-01-01", "2012-01-01"],
                "input_inventory": {"path": str(raw), "sha256": capture_file_hash(raw)},
                "empty_years": [2009, 2011],
                "snapshot": [{"readonly": "on", "isolation": "repeatable read"}],
            }
        )
    )
    return freeze_prod_weekly_plan(
        ProdWeeklyScope(
            StockWeeklySource.PRIMARY_UNADJUSTED,
            inventories,
            str(proof),
            capture_file_hash(proof),
        )
    )


def test_empty_boundary_years_allow_full_audited_candidate(tmp_path):
    plan = frozen(tmp_path)
    assert len(verified_empty_inventory_intervals(plan)) == 2
    store = WeeklyCaptureStore(tmp_path / "capture", plan)
    frame = prod_frame(trade_date="20100101")
    with store.locked(), duckdb.connect() as con:
        unit = plan.units[0]
        attempt = store.begin_attempt(unit)
        chunk = store.write_chunk(con, frame, unit, attempt, 0)
        store.seal(con, unit, [chunk], 1, {"snapshot": "test"})
    audit_path = build_weekly_partition_candidates(
        plan,
        capture_root=tmp_path / "capture",
        target_root=tmp_path / "lake",
        year=2010,
    )
    audit = json.loads(audit_path.read_text())
    assert audit["stats"]["candidate_rows"] == 1
    assert audit["partial_scope"] is False
    assert len(audit["files"]) == 1
    assert not (tmp_path / "lake").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "not_readonly",
        "wrong_isolation",
        "wrong_source",
        "missing_empty_year",
        "nonempty_as_empty",
        "changed_rows",
    ],
)
def test_invalid_inventory_rejected_with_rehashed_file(tmp_path, mutation):
    plan = frozen(tmp_path)
    proof = tmp_path / "inventory.json"
    payload = json.loads(proof.read_text())
    if mutation == "not_readonly":
        payload["snapshot"][0]["readonly"] = "off"
    elif mutation == "wrong_isolation":
        payload["snapshot"][0]["isolation"] = "read committed"
    elif mutation == "wrong_source":
        payload["source"] = StockWeeklySource.PRIMARY_ADJUSTED.value
    elif mutation == "missing_empty_year":
        payload["empty_years"] = [2009]
    elif mutation == "nonempty_as_empty":
        payload["empty_years"] = [2009, 2010, 2011]
    else:
        payload["inventories"][1]["source_rows"] = 2
    proof.write_text(json.dumps(payload))
    # Even a caller updating the file hash cannot bypass the semantic checks.
    altered = replace(plan, evidence_hash=capture_file_hash(proof))
    with pytest.raises(WeeklyCaptureError, match="inventory_evidence_invalid"):
        verified_empty_inventory_intervals(altered)


def test_tampering_and_old_format_do_not_prove_empty_window(tmp_path):
    plan = frozen(tmp_path)
    proof = tmp_path / "inventory.json"
    proof.write_text("{}")
    with pytest.raises(WeeklyCaptureError, match="source_evidence_hash_mismatch"):
        verified_empty_inventory_intervals(plan)
    altered = replace(plan, evidence_hash=capture_file_hash(proof))
    with pytest.raises(WeeklyCaptureError, match="year_boundary_inventory_missing"):
        build_weekly_partition_candidates(
            altered,
            capture_root=tmp_path / "capture",
            target_root=tmp_path / "lake",
            year=2010,
        )
    assert not (tmp_path / "capture").exists()


def test_rebuilt_plan_cannot_claim_nonempty_source_year_is_empty(tmp_path):
    plan = frozen(tmp_path)
    proof = tmp_path / "inventory.json"
    payload = json.loads(proof.read_text())
    payload["inventories"][1].update(codes=[], source_rows=0)
    payload["empty_years"] = [2009, 2010, 2011]
    proof.write_text(json.dumps(payload))
    scope = ProdWeeklyScope(
        plan.source,
        tuple(
            ProdYearInventory(i["year"], tuple(i["codes"]), i["source_rows"])
            for i in payload["inventories"]
        ),
        str(proof),
        capture_file_hash(proof),
    )
    with pytest.raises(WeeklyCaptureError, match="inventory_evidence_invalid"):
        verified_empty_inventory_intervals(freeze_prod_weekly_plan(scope))


def test_underlying_source_control_change_is_rejected(tmp_path):
    plan = frozen(tmp_path)
    (tmp_path / "inventory.csv").write_text("changed")
    with pytest.raises(WeeklyCaptureError, match="source_evidence_hash_mismatch"):
        verified_empty_inventory_intervals(plan)
