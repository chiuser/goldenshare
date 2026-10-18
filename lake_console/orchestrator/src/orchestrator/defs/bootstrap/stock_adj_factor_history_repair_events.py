"""Human-readable R4 completion observations; no Lake reads or business execution."""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    approved_repair_asset_keys,
    atomic_repair_json,
    check_repair_cancel,
    check_repair_path,
    repair_hash,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
    repair_writer_lock,
)

METADATA_KEY = "goldenshare/adj_factor_history_repair"
VALIDATION_SCOPE = "本次25股批准范围，范围外行未改；未重验全市场普通检查"


def _require(condition, reason):
    if not condition:
        raise FactorRepairError("repair_registration_" + reason)


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _root(run_root):
    root = check_repair_path(Path(run_root))
    _require(root.parent.name == "stock_adj_factor_history_repair"
             and root.name.startswith("run_id=") and len(root.name) > 7, "root_invalid")
    return root


def _read_json(path):
    return json.loads(check_repair_path(path).read_text())


def _references(root, asset):
    return {
        "scope_reference": {"plan": str(root / "plan.json"), "asset_key": asset},
        "manifest_reference": str(root / "reports/promotion_manifest.csv"),
        "proof_reference": [str(root / "checkpoints/candidates"),
                            str(root / "checkpoints/promotions")],
    }


def read_completed_repair_summary(run_root, expected_plan_hash):
    """Consume trusted R4 metadata once, without reopening its output or input files."""
    root = _root(run_root)
    _require(_hash(expected_plan_hash), "plan_hash_invalid")
    plan = _read_json(root / "plan.json")
    checkpoint = _read_json(root / "checkpoint.json")
    _require(plan.get("version") == 2 and plan.get("run_root") == str(root)
             and plan.get("run_id") == root.name.removeprefix("run_id=")
             and plan.get("plan_hash") == expected_plan_hash
             and checkpoint.get("plan_hash") == expected_plan_hash, "source_binding_invalid")
    chain = checkpoint.get("candidate_chain", {})
    promotion = checkpoint.get("promotion", {})
    _require(promotion.get("status") == "FILES_COMPLETE_EVENTS_PENDING"
             and promotion.get("plan_hash") == expected_plan_hash
             and chain.get("plan_hash") == expected_plan_hash
             and _hash(chain.get("chain_hash")), "files_incomplete")
    expected_assets = set(approved_repair_asset_keys())
    units = plan["units"]
    _require(len(units) == len(expected_assets)
             and {u["asset_key"] for u in units} == expected_assets
             and set(chain.get("assets", [])) == expected_assets, "asset_scope_invalid")
    lake = Path(plan["lake_root"])
    _require(lake.is_absolute() and ".." not in lake.parts, "lake_reference_invalid")
    targets = {}
    for unit in units:
        for name in unit["target_paths"]:
            path = Path(name)
            _require(path.is_absolute() and ".." not in path.parts, "target_invalid")
            relative = path.relative_to(lake).as_posix()
            _require(relative not in targets, "target_duplicate")
            targets[relative] = unit["asset_key"]
    counts = {a: {"target_files": 0, "committed_files": 0, "skipped_files": 0,
                  "failed_files": 0} for a in sorted(expected_assets)}
    seen = set()
    with check_repair_path(root / "reports/promotion_manifest.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            asset, target, status = row["asset_key"], row["target_relative_path"], row["status"]
            _require(asset in counts and targets.get(target) == asset, "manifest_scope_invalid")
            _require(target not in seen, "manifest_duplicate")
            _require(status in {"COMMITTED", "SKIPPED"}
                     and all(_hash(row.get(k)) for k in (
                         "candidate_record_hash", "candidate_sha256", "preimage_sha256")),
                     "manifest_incomplete")
            seen.add(target)
            counts[asset]["target_files"] += 1
            counts[asset]["committed_files" if status == "COMMITTED" else "skipped_files"] += 1
    with check_repair_path(root / "reports/failures.csv").open(newline="") as stream:
        _require(next(csv.DictReader(stream), None) is None, "file_failures")
    committed = sum(v["committed_files"] for v in counts.values())
    skipped = sum(v["skipped_files"] for v in counts.values())
    _require(seen == set(targets) and all(v["target_files"] for v in counts.values())
             and promotion.get("completed") == len(seen) == chain.get("targets")
             and chain.get("candidate_files") == committed
             and chain.get("no_op_files") == skipped, "completion_counts_invalid")
    return {"version": 1, "run_root": str(root), "run_id": plan["run_id"],
            "plan_hash": expected_plan_hash, "chain_hash": chain["chain_hash"],
            "assets": [{"asset_key": a, **v} for a, v in counts.items()]}


def repair_completion_observations(summary):
    """Return stable JSON content, not file-level materializations or green checks."""
    root = _root(summary["run_root"])
    bodies = []
    for item in summary["assets"]:
        body = {"version": 1, "run_id": summary["run_id"],
                "plan_hash": summary["plan_hash"], "chain_hash": summary["chain_hash"],
                **item, "validation_scope": VALIDATION_SCOPE,
                **_references(root, item["asset_key"]), "ordinary_checks_reported": False}
        bodies.append({**body, "token": repair_hash(body)})
    return bodies


def _validate_report(report, root, expected_hash):
    _require(report.get("version") == 1 and report.get("run_root") == str(root)
             and report.get("run_id") == root.name.removeprefix("run_id=")
             and report.get("plan_hash") == expected_hash and _hash(expected_hash)
             and _hash(report.get("chain_hash"))
             and report.get("status") in {"pending", "complete"}, "report_binding_invalid")
    entries = report["entries"]
    _require(len(entries) == 31 and {e["content"]["asset_key"] for e in entries}
             == set(approved_repair_asset_keys()), "report_assets_invalid")
    ids = []
    for entry in entries:
        body = entry["content"]
        token = body.get("token")
        _require(_hash(token) and token == repair_hash({k: v for k, v in body.items() if k != "token"})
                 and all(body.get(k) == report[k] for k in ("run_id", "plan_hash", "chain_hash"))
                 and body.get("version") == 1 and body.get("ordinary_checks_reported") is False
                 and body.get("validation_scope") == VALIDATION_SCOPE
                 and all(body.get(k) == v for k, v in _references(root, body["asset_key"]).items()),
                 "report_content_invalid")
        _require(all(type(body.get(k)) is int and body[k] >= 0 for k in (
            "target_files", "committed_files", "skipped_files", "failed_files"))
            and body["failed_files"] == 0 and body["target_files"] > 0
            and body["target_files"] == body["committed_files"] + body["skipped_files"],
            "report_counts_invalid")
        before, storage_id = entry["before_storage_id"], entry["storage_id"]
        _require(before is None or type(before) is int and before >= 0, "report_position_invalid")
        _require(storage_id is None or type(storage_id) is int and storage_id > 0,
                 "report_id_invalid")
        if storage_id is not None:
            ids.append(storage_id)
    _require(len(ids) == len(set(ids)) and report["completed"] == len(ids)
             and (report["status"] != "complete" or len(ids) == 31), "report_counts_invalid")


def _description(body):
    return (f"25股修复完成：本资产替换{body['committed_files']}个文件，"
            f"无需修改{body['skipped_files']}个文件；范围和依据见附带记录。")


def _matches(record, body):
    observation = record.asset_observation
    value = getattr(observation.metadata.get(METADATA_KEY), "value", None)
    related = isinstance(value, dict) and (
        value.get("token") == body["token"] or (
            value.get("run_id") == body["run_id"] and value.get("asset_key") == body["asset_key"]))
    if related:
        _require(value == body and observation.asset_key == dg.AssetKey(body["asset_key"])
                 and observation.partition is None and observation.description == _description(body),
                 "event_content_conflict")
    return related


def _verify_ids(instance, entries):
    ready = [e for e in entries if e["storage_id"] is not None]
    if not ready:
        return
    ids = [e["storage_id"] for e in ready]
    records = instance.get_event_records(dg.EventRecordsFilter(
        event_type=dg.DagsterEventType.ASSET_OBSERVATION, storage_ids=ids), limit=len(ids))
    by_id = {r.storage_id: r for r in records}
    _require(set(by_id) == set(ids), "saved_event_missing")
    for entry in ready:
        _require(_matches(by_id[entry["storage_id"]], entry["content"]), "saved_event_mismatch")


def _latest(instance, body):
    rows = instance.fetch_observations(dg.AssetKey(body["asset_key"]), limit=1).records
    return rows[0] if rows else None


def _find_after(instance, body, before, latest, cancel):
    """Read only the finite observation interval after this attempt's saved position."""
    if latest is None or latest.storage_id <= before:
        return None
    cursor, found = None, []
    while True:
        check_repair_cancel(cancel)
        page = instance.fetch_observations(dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(body["asset_key"]), after_storage_id=before,
            before_storage_id=latest.storage_id + 1), limit=100, cursor=cursor, ascending=True)
        found.extend(r for r in page.records if _matches(r, body))
        _require(len(found) <= 1, "event_duplicate")
        if not page.has_more:
            return found[0] if found else None
        _require(page.cursor != cursor, "event_cursor_invalid")
        cursor = page.cursor


def _save(path, report):
    report["completed"] = sum(e["storage_id"] is not None for e in report["entries"])
    report["updated_at"] = time.time()
    atomic_repair_json(path, report)


def register_repair_completion(instance, run_root, expected_plan_hash, *, summary=None,
                               dry_run=True, cancel=None, progress=None):
    """Default preview; explicitly approved writes append observations and one own-run report."""
    root = _root(run_root)
    path = check_repair_path(root / "reports/r5-registration.json")
    began = time.monotonic()
    report = _read_json(path) if path.exists() else None
    if report is None:
        summary = summary if summary is not None else read_completed_repair_summary(root, expected_plan_hash)
        _require(summary["run_root"] == str(root) and summary["plan_hash"] == expected_plan_hash,
                 "summary_binding_invalid")
        report = {k: summary[k] for k in ("version", "run_root", "run_id", "plan_hash", "chain_hash")}
        report.update(status="pending", completed=0, entries=[
            {"content": body, "before_storage_id": None, "storage_id": None}
            for body in repair_completion_observations(summary)])
    _validate_report(report, root, expected_plan_hash)
    if dry_run:
        return {**report, "dry_run": True, "new_events": 0}
    new_events = 0
    with repair_writer_lock(root):
        if path.exists():
            report = _read_json(path)
            _validate_report(report, root, expected_plan_hash)
        _verify_ids(instance, report["entries"])
        if report["status"] == "complete":
            return {**report, "new_events": 0, "reused_events": 31,
                    "elapsed_seconds": time.monotonic() - began}
        if not path.exists():
            _save(path, report)
        for entry in report["entries"]:
            check_repair_cancel(cancel)
            if entry["storage_id"] is not None:
                continue
            body = entry["content"]
            latest = _latest(instance, body)
            before = entry["before_storage_id"]
            matched = (_find_after(instance, body, before, latest, cancel) if before is not None
                       else latest if latest is not None and _matches(latest, body) else None)
            if matched is None:
                check_repair_cancel(cancel)
                entry["before_storage_id"] = latest.storage_id if latest else 0
                _save(path, report)
                instance.report_runless_asset_event(dg.AssetObservation(
                    asset_key=body["asset_key"], partition=None, description=_description(body),
                    metadata={METADATA_KEY: dg.MetadataValue.json(body)}))
                new_events += 1
                latest = _latest(instance, body)
                matched = (latest if latest is not None and _matches(latest, body) else
                           _find_after(instance, body, entry["before_storage_id"], latest, cancel))
                _require(matched is not None, "event_readback_missing")
            entry["storage_id"] = matched.storage_id
            _save(path, report)
            if progress:
                progress({"asset_key": body["asset_key"], "completed": report["completed"],
                          "total": 31, "elapsed_seconds": time.monotonic() - began})
        _verify_ids(instance, report["entries"])
        report["status"] = "complete"
        _save(path, report)
    return {**report, "new_events": new_events, "reused_events": 31 - new_events,
            "elapsed_seconds": time.monotonic() - began}
