"""Explicit maintenance entry: prepare read-only, then apply the reviewed seven dates."""

import io
import time
from pathlib import Path

from orchestrator.defs.bootstrap.moneyflow_event_plan import (
    moneyflow_event_instance_identity,
)
from orchestrator.defs.bootstrap.moneyflow_history_metadata import (
    MoneyflowHistoryMetadataRequest,
    parse_moneyflow_history_metadata,
)
from orchestrator.defs.bootstrap.moneyflow_history_receive import (
    audit_history_day,
    history_candidate_connection,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_control import (
    CONTRACTS,
    CUTOFF,
    LIMITS,
    SCOPE,
    Control,
    Source,
    code_identity,
    digest,
    file_hash,
    read_json,
    report_progress,
    require,
    root_directory,
    save_json,
    target,
    validate_code,
    validate_plan,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_events import (
    accepted,
    baseline,
    facts,
    metadata,
    register,
    unchanged_baseline,
    valid_check,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_files import (
    audit_pair,
    candidates,
    final_candidates,
    keys,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_files import (
    publish as publish_files,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_sensors import (
    idle,
    same_sensor_snapshot,
    transition,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_writer_lock
from orchestrator.defs.io.moneyflow_update_publication import (
    assert_moneyflow_update_path,
    assert_moneyflow_update_roots,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def _metadata(source, dataset, dates, directory, control):
    directory.mkdir(parents=True, exist_ok=False)
    request = MoneyflowHistoryMetadataRequest(
        dataset, CUTOFF, directory / "source.sql", tuple(dates)
    )
    with io.BytesIO() as buffer:
        source.metadata(request, buffer, control.check)
        require(buffer.tell() <= 1024**2, "metadata_size")
        return parse_moneyflow_history_metadata(
            buffer.getvalue(), dataset, CUTOFF, selected_dates=tuple(dates)
        )


def prepare_moneyflow_history_supplement(
    *,
    instance,
    source,
    updates,
    lake_root,
    staging_root,
    operation_id,
    expected_keys,
    source_evidence,
    scratch_root,
):
    """Read seven exact targets and five metadata requests. Only scratch is written."""
    lake_root, staging_root, scratch_root = map(
        Path, (lake_root, staging_root, scratch_root)
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    assert_moneyflow_update_path(scratch_root)
    require(
        any(
            p in scratch_root.parents
            for p in (Path("/private/tmp"), Path("/tmp").resolve())
        )
        and not scratch_root.exists(),
        "scratch_root",
    )
    root_directory(staging_root, operation_id)
    require(set(expected_keys) == {(d, t) for d, t, _ in SCOPE}, "scope")
    scratch_root.mkdir(parents=True)
    plan = {
        "revision": "moneyflow_supplement_v1",
        "limits": LIMITS,
        "lake_root": str(lake_root),
        "staging_root": str(staging_root),
        "operation_id": operation_id,
        "source_evidence": source_evidence,
        "instance": moneyflow_event_instance_identity(instance, lake_root),
        "code": code_identity(),
        "entries": [],
        "metadata": {},
    }
    control = Control(plan, digest(plan))
    control.state["counts"]["connections"] = control.state["counts"]["metadata"] = 0
    counted_source = Source(source, control)
    plan["sensors"] = control.read(updates.snapshot)
    idle(instance, control)
    for dataset in dict.fromkeys(d for d, _, _ in SCOPE):
        dates = sorted(t for d, t, _ in SCOPE if d == dataset)
        plan["metadata"][dataset] = _metadata(
            counted_source, dataset, dates, scratch_root / dataset, control
        )
    for dataset, day, expected_count in SCOPE:
        entry = {
            "dataset": dataset,
            "day": day,
            "keys": expected_keys[(dataset, day)],
            "baseline": {},
        }
        paths = {
            layer: target(lake_root, dataset, day, layer) for layer in ("raw", "silver")
        }
        hashes = {layer: file_hash(path) for layer, path in paths.items()}
        require(
            all(hashes.values())
            if dataset == "moneyflow_dc"
            else not any(hashes.values()),
            "baseline_presence",
        )
        for layer in paths:
            entry["baseline"][layer] = {
                "hash": hashes[layer],
                **baseline(instance, entry, layer, hashes[layer], control),
            }
        if dataset == "moneyflow_dc":
            with history_candidate_connection(scratch_root, control.check) as db:
                old_count = audit_history_day(
                    db, paths["raw"], paths["silver"], day, dataset=dataset
                )
                require(
                    set(keys(db, paths["raw"], dataset)).issubset(entry["keys"]),
                    "old_key_missing_from_source",
                )
                require(
                    old_count == 2812
                    if lake_root == Path(DEFAULT_LAKE_ROOT)
                    else 0 < old_count < len(entry["keys"]),
                    "old_row_count",
                )
            entry["old_rows"] = old_count
        facts = [
            f for f in plan["metadata"][dataset]["facts"] if f["trade_date"] == day
        ]
        require(
            len(facts) == 1 and facts[0]["rows"] == len(entry["keys"]), "metadata_count"
        )
        if lake_root == Path(DEFAULT_LAKE_ROOT):
            require(len(entry["keys"]) == expected_count, "formal_source_rows_changed")
        contract = CONTRACTS[dataset]
        entry["partition_exists"] = control.read(
            instance.has_dynamic_partition, contract.partition_set, day
        )
        require(
            dataset != "moneyflow_dc" or entry["partition_exists"],
            "old_partition_missing",
        )
        plan["entries"].append(entry)
    plan["preparation_reads"] = control.state["counts"]["reads"]
    plan["preparation_seconds"] = control.state["seconds"]
    validate_plan(plan, digest(plan))
    return plan


def _readback(plan, control, instance):
    for index, entry in enumerate(plan["entries"]):
        item = control.state["items"][str(index)]
        require(item.get("accepted") is True, "not_accepted")
        paths = {
            layer: target(
                Path(plan["lake_root"]), entry["dataset"], entry["day"], layer
            )
            for layer in ("raw", "silver")
        }
        require(
            all(
                file_hash(path) == item["hashes"][layer]
                for layer, path in paths.items()
            ),
            "accepted_file_changed",
        )
        with history_candidate_connection(
            Path(plan["staging_root"]), control.check
        ) as db:
            audit_pair(db, entry, paths)
        accepted(instance, entry, item["hashes"], control)


def _review_partial(plan, control, instance, *, indices=range(7)):
    """An interrupted operation is reviewed against native facts, not its journal alone."""
    for index, entry in enumerate(plan["entries"]):
        if index not in indices:
            continue
        item = control.state["items"].get(str(index), {})
        for layer in ("raw", "silver"):
            old = entry["baseline"][layer]
            new_hash = item.get("hashes", {}).get(layer)
            actual = file_hash(
                target(Path(plan["lake_root"]), entry["dataset"], entry["day"], layer)
            )
            require(actual in {old["hash"], new_hash}, "partial_target_changed")
            mat, check = facts(instance, entry, layer, control)
            if (mat.storage_id if mat else None) == old["mat_id"]:
                require(
                    (check.id if check else None) == old["check_id"],
                    "partial_check_changed",
                )
            else:
                require(
                    mat is not None
                    and new_hash is not None
                    and actual == new_hash
                    and metadata(mat).get("supplement_plan_sha256") == control.sha
                    and metadata(mat).get("file_sha256") == new_hash,
                    "partial_native_changed",
                )
                require(
                    (check.id if check else None) == old["check_id"]
                    or valid_check(mat, check, sha=control.sha, file_sha=new_hash),
                    "partial_check_changed",
                )
        if item.get("accepted"):
            accepted(instance, entry, item["hashes"], control)


def _candidate_manifest(control):
    return {
        "plan_sha256": control.sha,
        "entries": [
            {
                "index": i,
                "hashes": control.state["items"][str(i)]["hashes"],
                "proof_sha256": control.state["items"][str(i)]["proof_sha256"],
            }
            for i in range(7)
        ],
    }


def _prepare_candidates(plan, source, updates, control, instance, root, staging):
    lake = Path(plan["lake_root"])
    require(
        all(
            file_hash(target(lake, e["dataset"], e["day"], layer))
            == e["baseline"][layer]["hash"]
            for e in plan["entries"]
            for layer in ("raw", "silver")
        ),
        "cannot_prepare_after_publication",
    )
    counted_source = Source(source, control)
    for index, entry in enumerate(plan["entries"]):
        control.state.update(
            stage="building_candidates", current=[entry["dataset"], entry["day"]]
        )
        control.check()
        item = control.state["items"].setdefault(str(index), {})
        source_fact = candidates(entry, plan, counted_source, control)
        require(
            not item.get("source") or item["source"] == source_fact,
            "source_proof_changed",
        )
        item["source"] = source_fact
        control.disk()
        control.save()
    if not control.state["post_metadata"]:
        verified_metadata = control.state.setdefault("verified_metadata", {})
        for dataset, before in plan["metadata"].items():
            if dataset in verified_metadata:
                require(
                    verified_metadata[dataset] == digest(before),
                    "post_metadata_changed",
                )
                continue
            sequence = control.state["counts"]["metadata"]
            after = _metadata(
                counted_source,
                dataset,
                before["selected_dates"],
                root / f"metadata-{sequence}-{dataset}",
                control,
            )
            require(after == before, "source_metadata_changed")
            verified_metadata[dataset] = digest(after)
            control.save()
        control.state["post_metadata"] = True
        control.save()
    for index, entry in enumerate(plan["entries"]):
        item = control.state["items"][str(index)]
        directory = root / f"item-{index}"
        directory.mkdir(exist_ok=True)
        with moneyflow_writer_lock(staging / "moneyflow"):
            proof = final_candidates(
                entry, item["source"], plan, item, directory, control
            )
            paths = {k: Path(v) for k, v in proof["paths"].items()}
            require(
                all(file_hash(paths[k]) == proof["hashes"][k] for k in paths),
                "final_candidate_changed",
            )
            with history_candidate_connection(directory, control.check) as db:
                audit_pair(db, entry, paths)
        control.disk()
    manifest = _candidate_manifest(control)
    path = root / "candidates.json"
    if path.exists():
        require(read_json(path) == manifest, "candidate_manifest_changed")
    else:
        save_json(path, manifest)
    require(
        all(
            file_hash(target(lake, e["dataset"], e["day"], layer))
            == e["baseline"][layer]["hash"]
            for e in plan["entries"]
            for layer in ("raw", "silver")
        ),
        "target_changed_during_preparation",
    )
    idle(instance, control)
    transition(updates, control, restore=True)
    control.state["stage"] = "candidates_ready_for_review"
    control.save()
    return {
        "stage": control.state["stage"],
        "accepted": 0,
        "candidates_sha256": digest(manifest),
        "counts": control.state["counts"],
    }


def apply_moneyflow_history_supplement(
    plan,
    expected_plan_sha,
    *,
    instance,
    source,
    updates,
    apply=False,
    publish=False,
    expected_candidates_sha=None,
    sample_only=False,
    cancel=lambda: False,
    clock=time.monotonic,
    progress=report_progress,
    source_review=None,
    expected_source_review_sha=None,
):
    """No jobs or Tushare calls. Formal writes require separate operator authorization."""
    lake, staging = validate_plan(
        plan,
        expected_plan_sha,
        source_review=source_review,
        expected_source_review_sha=expected_source_review_sha,
    )
    require(
        moneyflow_event_instance_identity(instance, lake) == plan["instance"],
        "instance_changed",
    )
    root = root_directory(staging, plan["operation_id"])
    review_path = root / "source-review.json"
    require(
        source_review is not None or not review_path.exists(), "source_review_missing"
    )
    if source_review is not None:
        require(
            (root / "candidates.json").is_file()
            and digest(read_json(root / "candidates.json"))
            == source_review["candidates_sha256"],
            "source_review_candidates",
        )
        if review_path.exists():
            require(
                read_json(review_path) == source_review, "saved_source_review_changed"
            )
    control = Control(
        plan, expected_plan_sha, cancel=cancel, clock=clock, progress=progress
    )
    if (root / "state.json").exists():
        control.state = read_json(root / "state.json")
        require(control.state["plan_sha"] == expected_plan_sha, "state_plan")
        saved_review = control.state.get("source_review_sha")
        if saved_review is not None:
            require(
                saved_review == expected_source_review_sha and review_path.is_file(),
                "saved_source_review_missing",
            )
        if len(control.state["items"]) == 7 and all(
            i.get("accepted") for i in control.state["items"].values()
        ):
            _readback(plan, control, instance)
            if control.state["stage"] == "complete":
                require(
                    same_sensor_snapshot(
                        control.read(updates.snapshot), plan["sensors"]
                    ),
                    "restored_sensors_changed",
                )
                return {"stage": "complete", "accepted": 7, "replay": True, "writes": 0}
    if not (root / "state.json").exists():
        for entry in plan["entries"]:
            for layer in ("raw", "silver"):
                require(
                    file_hash(target(lake, entry["dataset"], entry["day"], layer))
                    == entry["baseline"][layer]["hash"],
                    "target_changed",
                )
                unchanged_baseline(instance, entry, layer, control)
        require(
            same_sensor_snapshot(control.read(updates.snapshot), plan["sensors"]),
            "sensor_baseline_changed",
        )
        idle(instance, control)
    if not apply:
        if (root / "state.json").exists():
            _review_partial(plan, control, instance)
        return {
            "stage": "reviewed",
            "accepted": sum(
                i.get("accepted", False) for i in control.state["items"].values()
            ),
            "plan_sha256": expected_plan_sha,
            "writes": 0,
        }
    if publish:
        require(
            (root / "candidates.json").is_file()
            and expected_candidates_sha is not None,
            "candidate_approval_missing",
        )
        manifest = read_json(root / "candidates.json")
        require(
            digest(manifest) == expected_candidates_sha
            and manifest == _candidate_manifest(control),
            "candidate_approval_changed",
        )
    root.mkdir(parents=True, exist_ok=True)
    with moneyflow_writer_lock(root):
        if not (root / "state.json").exists():
            save_json(root / "state.json", control.state)
        control = Control(
            plan, expected_plan_sha, root, cancel=cancel, clock=clock, progress=progress
        )
        if source_review is not None:
            if review_path.exists():
                require(
                    read_json(review_path) == source_review,
                    "saved_source_review_changed",
                )
            else:
                save_json(review_path, source_review)
            require(
                control.state.get("source_review_sha")
                in (None, expected_source_review_sha),
                "saved_source_review_changed",
            )
            control.state["source_review_sha"] = expected_source_review_sha
        control.save()
        plan_file = root / "plan.json"
        if plan_file.exists():
            require(read_json(plan_file) == plan, "saved_plan_changed")
        else:
            save_json(plan_file, plan)
        try:
            transition(updates, control)
            idle(instance, control, wait=True)
            if not publish:
                return _prepare_candidates(
                    plan, source, updates, control, instance, root, staging
                )
            require(
                read_json(root / "candidates.json") == _candidate_manifest(control),
                "candidate_manifest_changed",
            )
            for index, entry in enumerate(plan["entries"]):
                validate_code(
                    plan, expected_plan_sha, source_review, expected_source_review_sha
                )
                if source_review is not None:
                    require(
                        read_json(review_path) == source_review,
                        "saved_source_review_changed",
                    )
                if sample_only and index:
                    control.state["stage"] = "sample_accepted_updates_paused"
                    control.save()
                    return {"stage": control.state["stage"], "accepted": 1}
                item = control.state["items"][str(index)]
                control.state.update(
                    current=[entry["dataset"], entry["day"]], stage="publishing"
                )
                directory = root / f"item-{index}"
                directory.mkdir(exist_ok=True)
                with moneyflow_writer_lock(staging / "moneyflow"):
                    if item.get("accepted"):
                        accepted(instance, entry, item["hashes"], control)
                        continue
                    _review_partial(plan, control, instance, indices=(index,))
                    require(
                        file_hash(Path(item["source"]["receipt"]))
                        == item["source"]["receipt_sha256"],
                        "source_receipt_changed",
                    )
                    # Recheck switches after source generation; no shared writer can run.
                    require(
                        all(
                            v["status"] == "STOPPED"
                            for v in control.read(updates.snapshot).values()
                        ),
                        "updates_not_paused",
                    )
                    proof = final_candidates(
                        entry, item["source"], plan, item, directory, control
                    )
                    paths = publish_files(entry, plan, proof, directory, control)
                    control.state["stage"] = "registering"
                    register(instance, entry, paths, proof["hashes"], control)
                    item["accepted"] = True
                    control.save()
            _readback(plan, control, instance)
            transition(updates, control, restore=True)
            control.state["stage"] = "complete"
            control.save()
            return {
                "stage": "complete",
                "accepted": 7,
                "counts": control.state["counts"],
            }
        except BaseException:
            control.state["stage"] = "stopped_review_required"
            control.save()
            untouched = all(
                file_hash(target(lake, e["dataset"], e["day"], layer))
                == e["baseline"][layer]["hash"]
                for e in plan["entries"]
                for layer in ("raw", "silver")
            )
            if untouched:
                control.cancel = lambda: False
                idle(instance, control)
                transition(updates, control, restore=True)
            raise
