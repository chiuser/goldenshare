"""Independent byte accounting and reuse evidence on task-owned temporary files."""

from dataclasses import asdict
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    file_identity,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import (
    repair_storage_totals,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_runtime import (
    RepairRuntime,
    RepairStorageLedger,
    replace_repair_file,
    use_repair_runtime,
    write_repair_json,
)


def plan_for(root):
    return {"run_root": str(root), "lake_root": str(root / "lake"),
            "plan_hash": "isolated-literal-plan", "source_fingerprints": [],
            "target_preimages": [], "units": []}


def test_incremental_bytes_and_reservations_never_rescan_between_writes(tmp_path):
    scans = []
    def scan(root):
        scans.append(root)
        return repair_storage_totals(root)
    runtime = RepairRuntime(plan_for(tmp_path))
    runtime.storage = RepairStorageLedger(tmp_path, scan=scan, plan=runtime.plan)
    output = tmp_path / "candidates/result.parquet.partial"
    output.parent.mkdir()
    with use_repair_runtime(runtime):
        with runtime.storage.writing(output, candidate=True, reserve_bytes=4):
            output.write_bytes(b"1234")
        renamed = output.with_suffix("")
        replace_repair_file(output, renamed)
        write_repair_json(tmp_path / "checkpoints/active.json", {"completed": 1})
        for _ in range(20):
            assert runtime.storage.check()["candidate_bytes"] == 4
        assert scans == [tmp_path]
        expected = repair_storage_totals(tmp_path)
        assert runtime.storage.snapshot() == expected
        assert runtime.storage.reconcile() == expected
        assert scans == [tmp_path, tmp_path]


def test_reservation_recovery_stats_only_the_unsettled_path(tmp_path):
    plan = plan_for(tmp_path)
    ledger = RepairStorageLedger(tmp_path, scan=repair_storage_totals, plan=plan)
    output = tmp_path / "candidates/partial.parquet"
    output.parent.mkdir()
    ledger.pending = {"path": str(output), "before": 0, "reserved": 6}
    ledger.persist()
    output.write_bytes(b"123456")  # Simulates exit after reservation, before settlement.
    def forbidden_scan(_root):
        raise AssertionError("a durable reservation does not require a directory scan")
    restored = RepairStorageLedger(tmp_path, scan=forbidden_scan, plan=plan)
    assert restored.counts["candidate_bytes"] == 6 and restored.pending is None
    assert restored.snapshot() == repair_storage_totals(tmp_path)
    restored.persist()
    assert RepairStorageLedger(tmp_path, scan=forbidden_scan, plan=plan).snapshot() == restored.snapshot()


def test_final_accounting_rejects_untracked_file_without_scanning_market(tmp_path):
    ledger = RepairStorageLedger(tmp_path, scan=repair_storage_totals, plan=plan_for(tmp_path))
    (tmp_path / "untracked").write_bytes(b"1")
    with pytest.raises(FactorRepairError, match="accounting_mismatch"):
        ledger.reconcile()


def test_cached_identity_uses_strong_hash_once_and_a_new_runtime_rejects_tampering(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"original")
    expected = asdict(file_identity(path))
    plan = {**plan_for(tmp_path), "source_fingerprints": [expected]}
    runtime = RepairRuntime(plan)
    for _ in range(20):
        assert runtime.verify_source(path) == path
    assert runtime.counters["hash_files"] == 1
    info = path.stat()
    path.write_bytes(b"tampered")
    import os
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(FactorRepairError, match="input_drift"):
        RepairRuntime(plan).verify_source(path)


def test_failed_write_settles_actual_bytes_and_preserves_output(tmp_path):
    ledger = RepairStorageLedger(tmp_path, scan=repair_storage_totals, plan=plan_for(tmp_path))
    output = tmp_path / "candidates/failed.partial"
    output.parent.mkdir()
    with pytest.raises(OSError, match="injected"), ledger.writing(output, candidate=True, reserve_bytes=100):
        output.write_bytes(b"123")
        raise OSError("injected")
    assert output.read_bytes() == b"123"
    assert ledger.pending is None and ledger.counts["candidate_bytes"] == 3
    assert ledger.snapshot() == repair_storage_totals(tmp_path)


def test_json_reservation_recovers_only_its_exact_owned_temporary(tmp_path):
    plan = plan_for(tmp_path)
    ledger = RepairStorageLedger(tmp_path, scan=repair_storage_totals, plan=plan)
    target = tmp_path / "checkpoints/record.json"
    target.parent.mkdir()
    temporary = Path(str(target) + ".partial")
    ledger.pending = {"path": str(target), "before": 0, "reserved": 20, "temporary": str(temporary)}
    ledger.persist()
    temporary.write_bytes(b'{"incomplete":')
    unrelated = tmp_path / "unrelated"
    unrelated.write_bytes(b"kept")
    restored = RepairStorageLedger(tmp_path, scan=lambda root: pytest.fail("unexpected rescan"), plan=plan)
    assert restored.pending is None and not temporary.exists()
    assert unrelated.read_bytes() == b"kept"  # No directory cleanup or guessed ownership.


@pytest.mark.parametrize("size", [0, 1])
def test_admitted_run_census_rejects_unknown_artifacts_including_empty_files(tmp_path, size):
    runtime = RepairRuntime(plan_for(tmp_path), admitted=True)
    (tmp_path / "unknown.parquet").write_bytes(b"x" * size)
    with use_repair_runtime(runtime), pytest.raises(FactorRepairError, match="unowned_artifact"):
        RepairStorageLedger(tmp_path, scan=repair_storage_totals, plan=runtime.plan)
