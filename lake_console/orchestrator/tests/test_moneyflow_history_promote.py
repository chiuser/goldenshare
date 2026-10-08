"""Isolated formal-layout stand-ins; no Prod, Lake, instance or network access."""

import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap import moneyflow_history_promote as promote
from orchestrator.defs.bootstrap.moneyflow_history_cohort import (
    build_moneyflow_history_cohort_candidates,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import history_schema
from orchestrator.defs.paths import (
    PATH_TEMPLATE_PARTITION_KEY,
    raw_moneyflow_path,
    silver_moneyflow_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_DATASETS as DATASETS,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

DAY = "2026-09-30"


class Source:
    def __init__(self, rows=None):
        self.calls = 0
        self.rows = rows or {dataset: [self.row(dataset)] for dataset in DATASETS}

    @staticmethod
    def row(dataset):
        row = {
            c.name: "0" if c.type != "VARCHAR" else None
            for c in history_schema(dataset)
        }
        row["trade_date"] = DAY
        if "ts_code" in row:
            row["ts_code"] = "000001.SZ"
        if "name" in row:
            row["name"] = '名称,"逗号\n和换行'
        if dataset == "moneyflow_ind_dc":
            row.update(content_type="行业", ts_code=None)
        return row

    def metadata(self, request, sink, check):
        self.calls += 1
        request.sql()
        counts = {}
        for row in self.rows[request.dataset]:
            key = (
                row["trade_date"],
                row["content_type"] if request.dataset == "moneyflow_ind_dc" else "",
            )
            counts[key] = counts.get(key, 0) + 1
        snapshot = {
            "dataset": request.dataset,
            "cutoff": DAY,
            "relation_kind": "r",
            "columns": [
                [
                    c.name,
                    "date"
                    if c.name == "trade_date"
                    else "text"
                    if c.type == "VARCHAR"
                    else c.type.lower().replace("decimal", "numeric"),
                ]
                for c in history_schema(request.dataset)
            ],
            "facts": [
                {
                    "trade_date": day,
                    "scope": scope,
                    "rows": n,
                    "keys": n,
                    "invalid_keys": 0,
                }
                for (day, scope), n in sorted(counts.items())
            ],
        }
        sink.write(
            json.dumps(snapshot, ensure_ascii=False).encode().hex().encode() + b"\n"
        )
        check()

    def copy(self, request, sink, check):
        self.calls += 1
        request.sql()
        rows = [
            r
            for r in self.rows[request.plan.dataset]
            if r["trade_date"] in request.plan.units[request.unit_id].dates
        ]
        fields = [c.name for c in history_schema(request.plan.dataset)]
        handle = io.StringIO(newline="")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([r"\N" if row.get(f) is None else row[f] for f in fields])
        payload = handle.getvalue().encode()
        for offset in range(0, len(payload), 65536):
            sink.write(payload[offset : offset + 65536])
            check()


@pytest.fixture(autouse=True)
def isolated_space(monkeypatch):
    monkeypatch.setattr(
        engine.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**3)
    )


def setup(tmp_path, rows=None):
    source = Source(rows)
    staging, lake = tmp_path / "staging", tmp_path / "lake"
    lake.mkdir()
    result = build_moneyflow_history_cohort_candidates(
        staging_root=staging, operation_id="cohort", cutoff=DAY, source=source
    )
    assert result["stage"] == "candidates_verified"
    return staging, lake, source


def operation(staging):
    return staging / "moneyflow/cohort"


def run(staging, lake, **kwargs):
    return promote.promote_moneyflow_history_cohort(
        staging_root=staging,
        operation_id="cohort",
        cutoff=DAY,
        lake_root=lake,
        **kwargs,
    )


def progress(staging):
    return json.loads((operation(staging) / "progress.json").read_text())


def hashes(directory):
    return {
        str(p.relative_to(directory)): promote._hash_file(p, lambda: None)
        for p in directory.rglob("*.parquet")
    }


def test_default_preflight_and_seven_file_promotion_replay(tmp_path):
    staging, lake, source = setup(tmp_path)
    candidate_bytes = sum(
        p.stat().st_size for p in operation(staging).rglob("*.parquet")
    )
    raw_checkpoints = {
        p: p.read_bytes() for p in operation(staging).rglob("checkpoint.json")
    }
    planned = run(staging, lake)
    assert planned["new_files"] == planned["total_files"] == 14
    assert planned["apply"] is False and not list(lake.rglob("*.parquet"))
    assert planned["percentage"] == 0
    result = run(staging, lake, apply=True)
    assert result["stage"] == "files_complete" and result["promoted_files"] == 14
    assert result["promoted_units"] == 7 and result["percentage"] == 100
    assert result["promoted_dates"] == result["promoted_rows"] == 7
    assert result["copy_transactions"] == source.calls == 28
    assert not list(operation(staging).rglob("*.parquet"))
    assert len(hashes(lake)) == 14
    assert result["retained_bytes"] >= candidate_bytes
    assert raw_checkpoints == {p: p.read_bytes() for p in raw_checkpoints}
    expected = hashes(lake)
    replay = run(staging, lake, apply=True)
    assert hashes(lake) == expected and replay["promoted_files"] == 14
    assert replay["retained_bytes"] >= candidate_bytes
    assert replay["copy_transactions"] == 28
    saved_control = (operation(staging) / "progress.json").read_bytes()
    with pytest.raises(MoneyflowContractError, match="history_promotion_started"):
        build_moneyflow_history_cohort_candidates(
            staging_root=staging, operation_id="cohort", cutoff=DAY, source=source
        )
    assert source.calls == 28
    assert (operation(staging) / "progress.json").read_bytes() == saved_control


@pytest.mark.parametrize("dataset", DATASETS)
def test_path_contracts_and_unknown_rejection(tmp_path, dataset):
    assert (
        raw_moneyflow_path(tmp_path, dataset, DAY)
        == tmp_path / "raw/tushare" / dataset / f"trade_date={DAY}/part-000.parquet"
    )
    assert (
        silver_moneyflow_path(tmp_path, dataset, DAY)
        == tmp_path
        / "silver/moneyflow"
        / dataset
        / f"trade_date={DAY}/part-000.parquet"
    )
    assert "trade_date={partition_key}" in str(
        raw_moneyflow_path(tmp_path, dataset, PATH_TEMPLATE_PARTITION_KEY)
    )
    with pytest.raises(ValueError):
        raw_moneyflow_path(tmp_path, "../unknown", DAY)
    with pytest.raises(ValueError):
        silver_moneyflow_path(tmp_path, dataset, "2026-09-31")


@pytest.mark.parametrize(
    "kind",
    (
        "conflict",
        "neighbor",
        "candidate",
        "receipt",
        "unverified",
        "cross_device",
        "scope",
        "source_proof",
    ),
)
def test_preflight_refuses_entire_scope_before_any_write(tmp_path, monkeypatch, kind):
    staging, lake, _ = setup(tmp_path)
    candidate = next(
        operation(staging).glob(
            "moneyflow_ths/*/history_candidates/unit-*/*/*/raw.parquet"
        )
    )
    target = raw_moneyflow_path(lake, "moneyflow_ths", DAY)
    target.parent.mkdir(parents=True)
    if kind == "conflict":
        target.write_bytes(b"other")
    if kind == "neighbor":
        target.with_name("extra.parquet").write_bytes(b"other")
    if kind == "candidate":
        candidate.write_bytes(b"bad")
    if kind == "receipt":
        cp = next(operation(staging).rglob("checkpoint.json"))
        cp.write_text(cp.read_text() + " ")
    if kind == "unverified":
        path = operation(staging) / "progress.json"
        value = json.loads(path.read_text())
        value["completed_units"] = 0
        path.write_text(json.dumps(value))
    if kind == "cross_device":
        monkeypatch.setattr(promote, "_same_device", lambda *_: False)
    if kind in {"scope", "source_proof"}:
        cp = next(operation(staging).rglob("checkpoint.json"))
        value = json.loads(cp.read_text())
        if kind == "scope":
            value["dates"] = ["2026-09-29"]
        else:
            value["verification_proof"]["scope_counts"] = [[DAY, "概念", 1]]
        cp.write_text(json.dumps(value))
    baseline = hashes(lake)
    with pytest.raises(MoneyflowContractError):
        run(staging, lake, apply=True)
    assert hashes(lake) == baseline
    assert not list(operation(staging).rglob("promotion.json"))


def test_existing_identical_targets_reused_without_rewriting(tmp_path, monkeypatch):
    staging, lake, _ = setup(tmp_path)
    for ds in DATASETS:
        cp = next(
            operation(staging).glob(ds + "/*/history_candidates/unit-*/checkpoint.json")
        )
        receipt = json.loads(cp.read_text())
        base = cp.parent / receipt["attempt"] / DAY
        for layer, factory in (
            ("raw", raw_moneyflow_path),
            ("silver", silver_moneyflow_path),
        ):
            target = factory(lake, ds, DAY)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / (layer + ".parquet"), target)
    before = hashes(lake)
    original = promote.os.replace

    def forbid_parquet(source, target):
        assert Path(source).suffix != ".parquet"
        return original(source, target)

    monkeypatch.setattr(promote.os, "replace", forbid_parquet)
    result = run(staging, lake, apply=True)
    assert result["promoted_files"] == 14 and hashes(lake) == before
    assert len(list(operation(staging).rglob("*.parquet"))) == 14


@pytest.mark.parametrize("stage", ("before", "after_raw", "after_receipt"))
def test_cancel_retains_raw_and_resumes_without_source_requests(
    tmp_path, monkeypatch, stage
):
    staging, lake, source = setup(tmp_path)
    cancelled = [stage == "before"]
    original = promote.os.replace

    def move(source_path, target_path):
        original(source_path, target_path)
        if stage == "after_raw" and Path(source_path).name == "raw.parquet":
            cancelled[0] = True
        if stage == "after_receipt" and Path(target_path).name == "promotion.json":
            value = json.loads(Path(target_path).read_text())
            if any(item["status"] == "complete" for item in value["files"].values()):
                cancelled[0] = True

    monkeypatch.setattr(promote.os, "replace", move)
    with pytest.raises(InterruptedError):
        run(staging, lake, apply=True, cancel=lambda: cancelled[0])
    observed = hashes(lake)
    if stage == "after_raw":
        assert len(observed) == 1 and progress(staging)["stage"] == "interrupted"
        assert progress(staging)["promoted_dates"] == 0
        assert progress(staging)["promoted_rows"] == 0
    monkeypatch.setattr(promote.os, "replace", original)
    result = run(staging, lake, apply=True)
    assert result["promoted_files"] == 14 and source.calls == 28
    assert all(hashes(lake)[p] == digest for p, digest in observed.items())


def test_checkpoint_write_failure_does_not_rollback_formal_file(tmp_path, monkeypatch):
    staging, lake, _ = setup(tmp_path)
    original = engine._Store.json

    def fail(self, path, value):
        if path.name == "promotion.json" and any(
            item["status"] == "complete" for item in value["files"].values()
        ):
            raise OSError("isolated_state_failure")
        return original(self, path, value)

    monkeypatch.setattr(engine._Store, "json", fail)
    with pytest.raises(OSError, match="isolated_state_failure"):
        run(staging, lake, apply=True)
    assert len(hashes(lake)) == 1
    saved = progress(staging)
    assert saved["reservation_seconds"] == 0  # A caught error finishes its timed step.
    monkeypatch.setattr(engine._Store, "json", original)
    result = run(staging, lake, apply=True)
    assert result["charged_seconds"] >= saved["charged_seconds"]
    assert result["promoted_files"] == 14


@pytest.mark.parametrize(
    "kind",
    (
        "lake_change",
        "formal_tamper",
        "formal_missing",
        "promotion_tamper",
        "space",
        "time",
    ),
)
def test_resume_keeps_identity_physical_proof_and_budget(tmp_path, monkeypatch, kind):
    staging, lake, _ = setup(tmp_path)
    run(staging, lake, apply=True)
    if kind == "lake_change":
        lake = tmp_path / "different-lake"
        lake.mkdir()
    if kind == "formal_tamper":
        next(lake.rglob("*.parquet")).write_bytes(b"changed")
    if kind == "formal_missing":
        next(lake.rglob("*.parquet")).unlink()
    if kind == "promotion_tamper":
        path = next(operation(staging).rglob("promotion.json"))
        value = json.loads(path.read_text())
        value["candidate_checkpoint_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
    if kind == "space":
        monkeypatch.setattr(
            engine,
            "MONEYFLOW_HISTORY_MAX_DISK_BYTES",
            sum(p.stat().st_size for p in operation(staging).rglob("*") if p.is_file())
            + 1,
        )
    if kind == "time":
        path = operation(staging) / "progress.json"
        value = json.loads(path.read_text())
        value["charged_seconds"] = engine.MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS - 119
        path.write_text(json.dumps(value))
    with pytest.raises(MoneyflowContractError):
        run(staging, lake, apply=True)


@pytest.mark.parametrize(
    "kind", ("relative", "overlap", "wrong_root", "symlink", "neighbor_symlink")
)
def test_root_and_symlink_boundaries(tmp_path, kind):
    staging, lake, _ = setup(tmp_path)
    if kind == "relative":
        lake = Path("relative")
    if kind == "overlap":
        lake = staging
    if kind == "wrong_root":
        lake = Path("/Volumes/other-lake")
    if kind == "symlink":
        link = tmp_path / "lake-link"
        link.symlink_to(lake, target_is_directory=True)
        lake = link
    if kind == "neighbor_symlink":
        (lake / "raw").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(MoneyflowContractError):
        run(staging, lake, apply=True)


@pytest.mark.parametrize("phase", ("rename", "receipt"))
def test_actual_exit_new_process_recovers_moved_files_and_bytes(tmp_path, phase):
    staging, lake, _ = setup(tmp_path)
    script = tmp_path / "process.py"
    script.write_text("""
import json,os,sys
from pathlib import Path
from types import SimpleNamespace
from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap import moneyflow_history_promote as promote
engine.shutil.disk_usage=lambda _:SimpleNamespace(free=128*1024**3)
original=promote.os.replace
if sys.argv[3]!='resume':
    def exit_after(source,target):
        original(source,target)
        if sys.argv[3]=='rename' and Path(source).name=='raw.parquet':os._exit(23)
        if sys.argv[3]=='receipt' and Path(target).name=='promotion.json':
            state=json.loads(Path(target).read_text())
            if any(item['status']=='complete' for item in state['files'].values()):os._exit(23)
    promote.os.replace=exit_after
result=promote.promote_moneyflow_history_cohort(staging_root=Path(sys.argv[1]),lake_root=Path(sys.argv[2]),operation_id='cohort',cutoff='2026-09-30',apply=True)
print(json.dumps(result))
""")
    command = [sys.executable, "-B", str(script), str(staging), str(lake), phase]
    first = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert first.returncode == 23, first.stderr.decode()
    saved = progress(staging)
    assert saved["reservation_seconds"] == 120
    assert len(hashes(lake)) == 1
    before = hashes(lake)
    command[-1] = "resume"
    second = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert second.returncode == 0, second.stderr.decode()
    result = json.loads(second.stdout)
    assert result["promoted_files"] == 14 and result["stage"] == "files_complete"
    assert result["charged_seconds"] >= saved["charged_seconds"]
    assert result["retained_bytes"] >= sum(
        p.stat().st_size for p in lake.rglob("*.parquet")
    )
    assert all(hashes(lake)[p] == digest for p, digest in before.items())
    assert result["copy_transactions"] == 28


def test_moved_bytes_are_enforced_by_the_same_store_limit(tmp_path, monkeypatch):
    staging, lake, _ = setup(tmp_path)
    run(staging, lake, apply=True)
    root = operation(staging)
    manifest, units, closed, _ = promote._frozen(root, DAY)
    contract = promote._promotion_contract(manifest, closed, lake)
    moved = promote._moved_bytes(root, units, closed, contract, lake)
    assert moved == sum(p.stat().st_size for p in lake.rglob("*.parquet"))
    retained = engine._Store(root).used
    monkeypatch.setattr(
        engine, "MONEYFLOW_HISTORY_MAX_DISK_BYTES", retained + moved - 1
    )
    assert engine._Store(root).used == retained
    with pytest.raises(MoneyflowContractError, match="history_disk_bytes_budget"):
        engine._Store(
            root,
            external_bytes=lambda check: promote._moved_bytes(
                root, units, closed, contract, lake, check
            ),
        )


def test_matching_hashes_do_not_replace_current_unit_physical_audit(tmp_path):
    staging, lake, _ = setup(tmp_path)
    root = operation(staging)
    checkpoint = next((root / "moneyflow").rglob("checkpoint.json"))
    receipt = json.loads(checkpoint.read_text())
    candidate = checkpoint.parent / receipt["attempt"] / DAY / "silver.parquet"
    # Test-owned bytes, with matching receipts, must still fail schema/date audit.
    candidate.write_bytes(b"hash-consistent-but-not-parquet")
    receipt["files"][0]["silver_sha256"] = promote._hash_file(candidate, lambda: None)
    checkpoint.write_text(json.dumps(receipt))
    saved = progress(staging)
    saved["closed_units"][0]["checkpoint_sha256"] = promote._hash_file(
        checkpoint, lambda: None
    )
    (root / "progress.json").write_text(json.dumps(saved))
    with pytest.raises(MoneyflowContractError, match="history_columnar_error"):
        run(staging, lake, apply=True)
    assert not hashes(lake)
