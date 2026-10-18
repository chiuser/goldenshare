"""R5 metadata and native temporary Dagster events; never R4 formula acceptance.

Fixture fields come from the actual R4 plan version 2, checkpoint.candidate_chain /
promotion, and promotion_manifest.csv header documented in LLD §24.1/24.3.
Counts, scope, and expected descriptions below are independent literal examples.
"""

import csv
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_events as events
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
)

ASSETS = (
    "raw_tushare_adj_factor", "silver_adj_factor", "gold_stock_daily_qfq",
    "gold_stock_daily_trend_channel", "gold_stock_daily_trend_channel_state",
    "gold_stock_daily_qfq_nineturn",
    "gold_stk_mins_qfq_1m", "gold_stk_mins_qfq_5m", "gold_stk_mins_qfq_15m",
    "gold_stk_mins_qfq_30m", "gold_stk_mins_qfq_60m", "gold_stk_mins_qfq_90m",
    "gold_stk_mins_qfq_120m",
    "gold_stk_mins_qfq_macd_kdj_1m", "gold_stk_mins_qfq_macd_kdj_5m",
    "gold_stk_mins_qfq_macd_kdj_15m", "gold_stk_mins_qfq_macd_kdj_30m",
    "gold_stk_mins_qfq_macd_kdj_60m", "gold_stk_mins_qfq_macd_kdj_90m",
    "gold_stk_mins_qfq_macd_kdj_120m",
    "gold_stk_mins_qfq_macd_kdj_state_1m", "gold_stk_mins_qfq_macd_kdj_state_5m",
    "gold_stk_mins_qfq_macd_kdj_state_15m", "gold_stk_mins_qfq_macd_kdj_state_30m",
    "gold_stk_mins_qfq_macd_kdj_state_60m", "gold_stk_mins_qfq_macd_kdj_state_90m",
    "gold_stk_mins_qfq_macd_kdj_state_120m",
    "gold_stk_mins_qfq_nineturn_30m", "gold_stk_mins_qfq_nineturn_60m",
    "gold_stk_mins_qfq_nineturn_90m", "gold_stk_mins_qfq_nineturn_120m",
)
PLAN_HASH = "1" * 64
CHAIN_HASH = "2" * 64
RUN_ID = "11111111-1111-4111-8111-111111111111"
HEADER = ["asset_key", "target_relative_path", "status", "checkpoint_status",
          "preimage_sha256", "candidate_sha256", "candidate_record_hash",
          "changed_stock_rows", "approved_scope", "completed_at", "reason_code"]


def save(path, value):
    path.write_text(json.dumps(value))


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, HEADER + ["unrelated_optional_column"])
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "stock_adj_factor_history_repair" / ("run_id=" + RUN_ID)
    reports = root / "reports"
    reports.mkdir(parents=True)
    lake = tmp_path / "lake"
    units, rows = [], []
    for asset in ASSETS:
        # Shared dates and annual layouts are references only, never DG partitions.
        relative = (f"gold/{asset}/year=2025/data.parquet" if "mins" in asset
                    and "state" not in asset else
                    f"gold/{asset}/trade_date=2025-01-03/data.parquet")
        paths = [relative]
        if asset == "gold_stock_daily_qfq":
            paths.append(f"gold/{asset}/trade_date=2025-01-06/data.parquet")
        units.append({"asset_key": asset, "target_paths": [str(lake / p) for p in paths],
                      "calendar_dates": ["2025-01-03", "2025-01-06"]})
        for relative in paths:
            skipped = asset == "gold_stock_daily_qfq_nineturn"
            rows.append({"asset_key": asset, "target_relative_path": relative,
                         "status": "SKIPPED" if skipped else "COMMITTED",
                         "checkpoint_status": "COMMITTED", "preimage_sha256": "3" * 64,
                         "candidate_sha256": "4" * 64, "candidate_record_hash": "5" * 64,
                         "changed_stock_rows": "0" if skipped else "2",
                         "approved_scope": "literal isolated 25-stock scope",
                         "completed_at": "2026-10-18T00:00:00Z", "reason_code": "",
                         "unrelated_optional_column": "normal producer extension"})
    plan = {"version": 2, "run_id": RUN_ID, "run_root": str(root),
            "lake_root": str(lake), "plan_hash": PLAN_HASH, "units": units}
    checkpoint = {
        "plan_hash": PLAN_HASH,
        "candidate_chain": {"plan_hash": PLAN_HASH, "chain_hash": CHAIN_HASH,
                            "assets": list(ASSETS), "targets": 32,
                            "candidate_files": 31, "no_op_files": 1},
        "promotion": {"plan_hash": PLAN_HASH, "status": "FILES_COMPLETE_EVENTS_PENDING",
                      "completed": 32},
    }
    save(root / "plan.json", plan)
    save(root / "checkpoint.json", checkpoint)
    write_rows(reports / "promotion_manifest.csv", rows)
    (reports / "failures.csv").write_text("asset_key,target_relative_path,reason_code\n")
    return root, plan, checkpoint, rows


class NativeEvents:
    """Counts calls while all claimed writes and queries use native Dagster storage."""

    def __init__(self, instance):
        self.instance = instance
        self.writes = self.reads = 0

    def report_runless_asset_event(self, event):
        assert type(event) is dg.AssetObservation
        self.writes += 1
        return self.instance.report_runless_asset_event(event)

    def fetch_observations(self, *args, **kwargs):
        self.reads += 1
        return self.instance.fetch_observations(*args, **kwargs)

    def get_event_records(self, *args, **kwargs):
        self.reads += 1
        return self.instance.get_event_records(*args, **kwargs)

    def __getattr__(self, name):
        raise AssertionError("R5 must not use other instance operations: " + name)


@pytest.fixture
def native():
    with dg.DagsterInstance.ephemeral() as instance:
        yield NativeEvents(instance)


def register(native, root, **kwargs):
    return events.register_repair_completion(native, root, PLAN_HASH, dry_run=False, **kwargs)


def assert_unlocked(root):
    with (root.parent / "writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_UN)


def test_literal_summary_default_preview_and_no_source_access(case, native, monkeypatch):
    root, plan, _, _ = case
    original_open = Path.open

    def metadata_only(path, *args, **kwargs):
        assert not path.is_relative_to(Path(plan["lake_root"]))
        assert not str(path).endswith(".parquet")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    summary = events.read_completed_repair_summary(root, PLAN_HASH)
    assert len(summary["assets"]) == 31
    assert {row["asset_key"] for row in summary["assets"]} == set(ASSETS)
    assert sum(row["target_files"] for row in summary["assets"]) == 32
    assert sum(row["committed_files"] for row in summary["assets"]) == 31
    assert sum(row["skipped_files"] for row in summary["assets"]) == 1
    preview = events.register_repair_completion(native, root, PLAN_HASH, summary=summary)
    assert preview["dry_run"] is True and preview["new_events"] == 0
    explicit = events.register_repair_completion(native, root, PLAN_HASH,
                                                 summary=summary, dry_run=True)
    assert explicit["entries"] == preview["entries"] and explicit["new_events"] == 0
    assert native.reads == native.writes == 0
    assert not (root / "reports/r5-registration.json").exists()
    assert not (root.parent / "writer.lock").exists()
    qfq = next(e["content"] for e in preview["entries"]
               if e["content"]["asset_key"] == "gold_stock_daily_qfq")
    assert (qfq["target_files"], qfq["committed_files"], qfq["skipped_files"]) == (2, 2, 0)
    assert qfq["validation_scope"] == "本次25股批准范围，范围外行未改；未重验全市场普通检查"
    assert qfq["ordinary_checks_reported"] is False
    assert qfq["scope_reference"] == {"plan": str(root / "plan.json"),
                                      "asset_key": "gold_stock_daily_qfq"}
    token_content = {k: v for k, v in qfq.items() if k != "token"}
    expected_token = hashlib.sha256(json.dumps(
        token_content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert qfq["token"] == expected_token


def test_native_31_observations_cost_and_completed_replay(case, native, monkeypatch):
    root = case[0]
    originals = {p: p.read_bytes() for p in (root / "plan.json", root / "checkpoint.json",
                 root / "reports/promotion_manifest.csv", root / "reports/failures.csv")}
    real_open = Path.open
    input_reads = []

    def metadata_only(path, *args, **kwargs):
        assert not path.is_relative_to(Path(case[1]["lake_root"]))
        assert path.suffix != ".parquet"
        if path in originals:
            input_reads.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    # Preexisting non-observation history must survive; R5 has no API to create these.
    native.instance.report_runless_asset_event(dg.AssetMaterialization("gold_stock_daily_qfq"))
    prior = native.instance.get_event_records(dg.EventRecordsFilter(
        dg.DagsterEventType.ASSET_MATERIALIZATION), limit=10)
    progress = []
    began = time.monotonic()
    result = register(native, root, progress=progress.append)
    elapsed = time.monotonic() - began
    assert result["status"] == "complete" and result["completed"] == 31
    assert (result["new_events"], result["reused_events"], native.writes, native.reads) == (31, 0, 31, 63)
    assert [p["completed"] for p in progress] == list(range(1, 32))
    assert len({e["storage_id"] for e in result["entries"]}) == 31
    assert len(input_reads) == 4 and set(input_reads) == set(originals)
    for entry in result["entries"]:
        record = native.instance.get_event_records(dg.EventRecordsFilter(
            dg.DagsterEventType.ASSET_OBSERVATION, storage_ids=[entry["storage_id"]]), limit=1)[0]
        observation = record.asset_observation
        assert observation.partition is None
        assert observation.metadata[events.METADATA_KEY].value == entry["content"]
        assert set(observation.metadata) == {"goldenshare/adj_factor_history_repair"}
        if observation.asset_key == dg.AssetKey("gold_stock_daily_qfq"):
            assert observation.description == "25股修复完成：本资产替换2个文件，无需修改0个文件；范围和依据见附带记录。"
    assert native.instance.get_event_records(dg.EventRecordsFilter(
        dg.DagsterEventType.ASSET_MATERIALIZATION), limit=10) == prior
    assert native.instance.get_event_records(dg.EventRecordsFilter(
        dg.DagsterEventType.ASSET_CHECK_EVALUATION), limit=1) == []
    assert native.instance.get_runs() == []
    report_path = root / "reports/r5-registration.json"
    report_before = report_path.read_bytes(), report_path.stat().st_mtime_ns

    def no_reassembly(*args, **kwargs):
        raise AssertionError("completed replay must not re-read original R4 inputs")

    monkeypatch.setattr(events, "read_completed_repair_summary", no_reassembly)
    monkeypatch.setattr(events, "repair_completion_observations", no_reassembly)
    resumed = register(native, root)
    assert resumed["new_events"] == 0 and resumed["reused_events"] == 31
    assert native.writes == 31 and native.reads == 64
    assert (report_path.read_bytes(), report_path.stat().st_mtime_ns) == report_before
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert_unlocked(root)
    print(f"R5 isolated native registration: {elapsed:.4f}s; 31 writes, 63 reads; completed replay 1 read")


def test_other_writer_and_wrong_root_are_rejected(case, native, tmp_path):
    root = case[0]
    with (root.parent / "writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(FactorRepairError, match="writer_busy"):
            register(native, root)
    with pytest.raises(FactorRepairError, match="root_invalid"):
        register(native, tmp_path / "unrelated" / ("run_id=" + RUN_ID))
    assert native.reads == native.writes == 0
    assert not (root / "reports/r5-registration.json").exists()


@pytest.mark.parametrize("stop_after", [1, 16, 30])
def test_cancel_retains_completed_and_resumes_only_remaining(case, native, stop_after, monkeypatch):
    root = case[0]
    canceled = False

    def progress(value):
        nonlocal canceled
        canceled = value["completed"] == stop_after

    with pytest.raises(FactorRepairError, match="canceled"):
        register(native, root, cancel=lambda: canceled, progress=progress)
    assert native.writes == stop_after
    saved = json.loads((root / "reports/r5-registration.json").read_text())
    assert saved["completed"] == stop_after and saved["status"] == "pending"
    ids = [e["storage_id"] for e in saved["entries"] if e["storage_id"] is not None]
    assert_unlocked(root)
    monkeypatch.setattr(events, "read_completed_repair_summary",
                        lambda *a: pytest.fail("resume must reuse determined content"))
    result = register(native, root)
    assert result["new_events"] == 31 - stop_after and native.writes == 31
    assert ids == [e["storage_id"] for e in result["entries"][:stop_after]]


@pytest.mark.parametrize("failure", ["report_save", "uncertain_api"])
def test_event_saved_but_acknowledgement_failed_is_adopted(case, native, monkeypatch, failure):
    root = case[0]
    real_save = events.atomic_repair_json
    real_write = native.report_runless_asset_event

    def save_failure(path, report):
        if report["completed"] == 1:
            raise OSError("isolated report save failure")
        return real_save(path, report)

    def uncertain(event):
        real_write(event)
        raise OSError("isolated result lost after DG saved event")

    with monkeypatch.context() as patch:
        if failure == "report_save":
            patch.setattr(events, "atomic_repair_json", save_failure)
        else:
            patch.setattr(native, "report_runless_asset_event", uncertain)
        with pytest.raises(OSError, match="isolated"):
            register(native, root)
    assert native.writes == 1
    saved = json.loads((root / "reports/r5-registration.json").read_text())
    assert saved["completed"] == 0 and saved["entries"][0]["before_storage_id"] == 0
    assert_unlocked(root)
    resumed = register(native, root)
    assert resumed["status"] == "complete" and native.writes == 31
    assert resumed["new_events"] == 30 and resumed["reused_events"] == 1


def prepare_ambiguous(case, native, monkeypatch):
    root = case[0]
    real_save = events.atomic_repair_json

    def fail(path, report):
        if report["completed"] == 1:
            raise OSError("isolated acknowledgement failure")
        return real_save(path, report)

    with monkeypatch.context() as patch:
        patch.setattr(events, "atomic_repair_json", fail)
        with pytest.raises(OSError):
            register(native, root)
    entry = json.loads((root / "reports/r5-registration.json").read_text())["entries"][0]
    return entry["content"]


def test_foreign_observations_and_cursor_pagination_do_not_hide_saved_event(case, native, monkeypatch):
    body = prepare_ambiguous(case, native, monkeypatch)
    # More than one query page, no arbitrary lifetime cap; only finite pending interval.
    for number in range(101):
        native.instance.report_runless_asset_event(dg.AssetObservation(
            body["asset_key"], metadata={"other_purpose": number}))
    result = register(native, case[0])
    assert result["status"] == "complete" and native.writes == 31
    assert len(native.instance.fetch_observations(dg.AssetKey(body["asset_key"]), limit=200).records) == 102


@pytest.mark.parametrize("conflict", ["same_token_wrong_content", "same_run_new_token", "duplicate"])
def test_pending_real_conflicts_refuse_without_rewrite(case, native, monkeypatch, conflict):
    body = prepare_ambiguous(case, native, monkeypatch)
    changed = dict(body)
    if conflict == "same_token_wrong_content":
        changed["committed_files"] += 1
    elif conflict == "same_run_new_token":
        changed["token"] = "f" * 64
    native.instance.report_runless_asset_event(dg.AssetObservation(
        body["asset_key"], description=events._description(body),
        metadata={events.METADATA_KEY: dg.MetadataValue.json(changed)}))
    with pytest.raises(FactorRepairError, match="event_duplicate|event_content_conflict"):
        register(native, case[0])
    assert native.writes == 1


@pytest.mark.parametrize("fault", ["missing_id", "wrong_id", "body_tamper", "other_run"])
def test_completed_report_does_not_override_missing_or_inconsistent_events(case, native, fault):
    root = case[0]
    register(native, root)
    path = root / "reports/r5-registration.json"
    report = json.loads(path.read_text())
    if fault == "missing_id":
        report["entries"][0]["storage_id"] = 999999
    elif fault == "wrong_id":
        records = native.instance.fetch_observations(dg.AssetKey(ASSETS[0]), limit=1).records
        report["entries"][0]["storage_id"] = records[0].storage_id
    elif fault == "body_tamper":
        report["entries"][0]["content"]["failed_files"] = 1
    else:
        report["run_id"] = "another-run"
    save(path, report)
    with pytest.raises(FactorRepairError):
        register(native, root)
    assert native.writes == 31


@pytest.mark.parametrize("fault", ["wrong_hash", "wrong_run", "not_final", "failure_row",
    "duplicate", "missing", "out_of_scope", "unknown_asset"])
def test_invalid_completion_materials_stop_before_any_event(case, native, fault):
    root, plan, checkpoint, rows = case
    if fault == "wrong_hash":
        checkpoint["plan_hash"] = "a" * 64
    elif fault == "wrong_run":
        plan["run_id"] = "wrong"
    elif fault == "not_final":
        checkpoint["promotion"]["status"] = "RUNNING"
    elif fault == "failure_row":
        (root / "reports/failures.csv").write_text("asset_key,reason_code\nbad,failed\n")
    elif fault == "duplicate":
        rows.append(rows[0])
    elif fault == "missing":
        rows.pop()
    elif fault == "out_of_scope":
        rows[0]["target_relative_path"] = "../outside.parquet"
    else:
        rows[0]["asset_key"] = "not-approved"
    save(root / "plan.json", plan)
    save(root / "checkpoint.json", checkpoint)
    write_rows(root / "reports/promotion_manifest.csv", rows)
    with pytest.raises(FactorRepairError):
        register(native, root)
    assert native.reads == native.writes == 0
    assert not (root / "reports/r5-registration.json").exists()


@pytest.mark.parametrize("fault", ["root", "report", "source"])
def test_symlinks_are_rejected_without_events(case, native, tmp_path, fault):
    root = case[0]
    if fault == "root":
        link = root.parent / "run_id=link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif fault == "report":
        (root / "reports/r5-registration.json").symlink_to(root / "checkpoint.json")
    else:
        source = root / "plan.json"
        renamed = root / "original-plan.json"
        source.rename(renamed)
        source.symlink_to(renamed)
    with pytest.raises(FactorRepairError, match="symlink"):
        register(native, root)
    assert native.reads == native.writes == 0


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_real_process_exit_releases_lock_and_resumes_native_saved_events(case, tmp_path, termination):
    root = case[0]
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with dg.DagsterInstance.local_temp(tempdir=str(instance_dir)) as instance:
        child_code = """
import os, signal, sys
from dagster import DagsterInstance
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_events import register_repair_completion
def stop(value):
    if value['completed'] == 1:
        os.kill(os.getpid(), int(sys.argv[4]))
with DagsterInstance.from_config(sys.argv[1]) as instance:
    register_repair_completion(instance, sys.argv[2], sys.argv[3], dry_run=False, progress=stop)
"""
        child = subprocess.run([sys.executable, "-B", "-c", child_code, str(instance_dir),
                                str(root), PLAN_HASH, str(int(termination))],
                               capture_output=True, text=True, timeout=30, check=False,
                               env={**os.environ, "DAGSTER_HOME": str(instance_dir)})
        assert child.returncode == -termination, child.stderr
        saved = json.loads((root / "reports/r5-registration.json").read_text())
        assert saved["completed"] == 1
        assert_unlocked(root)
        native = NativeEvents(instance)
        result = register(native, root)
        assert result["status"] == "complete" and native.writes == 30
        assert result["entries"][0]["storage_id"] == saved["entries"][0]["storage_id"]
