"""Period Raw coordinator: fixed-root reset, capture, columnar build, commit and event resume."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import signal
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.io.stock_period_raw import (
    _BUDGET,
    StorageBudget,
    assemble,
    atomic_json,
    check_cancel,
    check_memory,
    connection,
    dataset_root,
    file_version,
    merge_ranges,
    process_memory_budget,
    publish,
    range_index_valid,
    read_json,
    safe_path,
    sync_directory,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    VERSION,
    admitted_code,
    digest,
    execution_id,
    period_date,
    verify_execution,
)
from orchestrator.defs.stock_period_source import HttpPage, capture_unit


def roots(root, staging):
    root = safe_path(root)
    staging = safe_path(staging)
    if (
        root == Path("/Volumes/datasource/data_lake")
        or staging == Path("/Volumes/datasource/data_lake_staging")
    ) and not os.path.ismount("/Volumes/datasource"):
        raise ValueError("period_formal_mount_missing")
    for path, formal in (
        (root, Path("/Volumes/datasource/data_lake")),
        (staging, Path("/Volumes/datasource/data_lake_staging")),
    ):
        if path != formal and (
            path == Path("/private/tmp") or not path.is_relative_to("/private/tmp")
        ):
            raise ValueError("period_root_forbidden")
    if root == staging or root.is_relative_to(staging) or staging.is_relative_to(root):
        raise ValueError("period_roots_overlap")
    return root, staging


def devices(root, staging):
    result = {}
    for label, path in (("root", root), ("staging", staging)):
        parent = safe_path(path)
        while not parent.exists():
            parent = parent.parent
        result[label] = parent.stat().st_dev
    if root == Path("/Volumes/datasource/data_lake"):
        if not os.path.ismount("/Volumes/datasource"):
            raise ValueError("period_formal_mount_missing")
        stat = Path("/Volumes/datasource").stat()
        result["mount"] = [stat.st_dev, stat.st_ino]
    return result


def check_devices(root, staging, expected):
    if devices(root, staging) != expected:
        raise ValueError("period_storage_device_changed")


_WRITER_LOCAL = threading.local()


@contextmanager
def writer(staging):
    control = safe_path(Path(staging) / "stock_period")
    control.mkdir(parents=True, exist_ok=True)
    owned = getattr(_WRITER_LOCAL, "owned", set())
    key = str(control)
    if key in owned:
        yield control
        return
    lock = safe_path(control / "writer.lock")
    with lock.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("period_writer_busy") from None
        previous = signal.getsignal(signal.SIGTERM)

        main = threading.current_thread() is threading.main_thread()

        def terminated(signum, frame):
            raise SystemExit(128 + signum)

        if main:
            signal.signal(signal.SIGTERM, terminated)
        _WRITER_LOCAL.owned = owned | {key}
        try:
            yield control
        finally:
            _WRITER_LOCAL.owned = owned
            if main:
                signal.signal(signal.SIGTERM, previous)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def remove_dataset(root, freq, cancel):
    """Metadata boundaries only. Never follow links or touch shared parents."""
    root = safe_path(root)
    if root == Path("/Volumes/datasource/data_lake") and not os.path.ismount(
        "/Volumes/datasource"
    ):
        raise ValueError("period_formal_mount_missing")
    if root != Path("/Volumes/datasource/data_lake") and (
        root == Path("/private/tmp") or not root.is_relative_to("/private/tmp")
    ):
        raise ValueError("period_root_forbidden")
    target = dataset_root(root, freq)
    if not target.exists():
        return

    # Validate the fixed target's descendants once before deletion; interruption may leave a suffix.
    def onerror(error):
        raise error

    for directory, dirs, files in os.walk(target, followlinks=False, onerror=onerror):
        check_cancel(cancel)
        for name in (*dirs, *files):
            safe_path(Path(directory) / name)
    check_cancel(cancel)
    # Per-entry unlink supports bounded cancellation without reading old business contents.
    for directory, dirs, files in os.walk(
        target, topdown=False, followlinks=False, onerror=onerror
    ):
        for name in files:
            check_cancel(cancel)
            safe_path(Path(directory) / name).unlink()
        for name in dirs:
            check_cancel(cancel)
            safe_path(Path(directory) / name).rmdir()
    check_cancel(cancel)
    target.rmdir()
    sync_directory(target.parent)


def _rss(policy):
    check_memory(policy)


def load_scope(root, work, policy=DEFAULT_POLICY):
    """Read the shared listed universe/confirmed identities once per execution."""
    from orchestrator.defs.paths import (
        silver_stock_basic_path,
        silver_stock_identity_map_path,
    )

    with connection(work, policy) as con:
        listed = {
            r[0]
            for r in con.execute(
                "SELECT ts_code FROM read_parquet(?) WHERE list_status='L' AND curr_type='CNY'",
                [str(silver_stock_basic_path(root))],
            ).fetchall()
        }
        identity = con.execute(
            "SELECT source_ts_code,latest_ts_code FROM read_parquet(?) WHERE confidence='confirmed'",
            [str(silver_stock_identity_map_path(root))],
        ).fetchall()
    aliases = dict(identity)
    for _, latest in identity:
        aliases[latest] = latest
    for code in listed:
        admitted_code(code, listed, aliases)
    return listed, aliases


def _record_ranges(baseline, run, intent, changed):
    """Compact source-derived ranges stay in the existing baseline, bound to its file inventory."""
    facts = read_json(baseline)
    maintain_index = intent["mode"] == "bootstrap" or range_index_valid(facts)
    if intent["mode"] == "bootstrap":
        facts["stock_ranges"] = {}
        facts["files"] = []
        facts["range_index_version"] = VERSION
    for freq in intent["frequencies"]:
        copied = read_json(run / "build" / freq / "copy.json")
        incoming = copied["stock_ranges"]
        if not copied["range_index_valid"]:
            facts.pop("range_index_version", None)
            maintain_index = False
        if not maintain_index:
            continue
        ranges = facts.setdefault("stock_ranges", {}).setdefault(freq, {})
        for code in intent.get("retired_codes", []) + intent.get(
            "superseded_codes", []
        ):
            ranges.pop(code, None)
        for code, intervals in incoming.items():
            ranges[code] = (
                intervals
                if intent["mode"] in ("bootstrap", "history")
                or code in intent.get("codes", [])
                else merge_ranges(ranges.get(code, []), intervals, freq)
            )
    files = {i["target"]: i for i in facts.get("files", [])}
    files.update(
        {
            i["target"]: {
                k: i[k] for k in ("freq", "period", "target", "version", "rows")
            }
            for i in changed
        }
    )
    facts["files"] = list(files.values())
    if maintain_index:
        facts["range_index_hash"] = digest({k: facts[k] for k in ("files", "stock_ranges")})
    else:
        facts.pop("range_index_version", None)
    atomic_json(baseline, facts)


def target_parent(path):
    parent = Path(path).parent
    while not parent.exists():
        parent = parent.parent
    return parent


def execution_time():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def completed_receipt(run, saved, *, cancel=lambda: False, complete=None):
    """Validate the immutable delivery without requiring its files to stay current."""
    run = safe_path(run)
    verify_execution(saved, run.name)
    # A caller may reuse a payload already read under its exact JSON stat guard.
    # Identity, hash, field and path checks below remain identical.
    if complete is None:
        complete = read_json(run / "complete.json")
    if (
        not isinstance(complete, dict)
        or complete.get("run_id") != run.name
        or run.name != execution_id(saved["identity"]["intent"]["request_id"])
        or saved.get("file_receipt_hash") != digest(complete)
        or not isinstance(complete.get("files"), list)
    ):
        raise ValueError("period_complete_receipt_changed")
    from orchestrator.defs.io.stock_period_raw import _target_path

    seen = set()
    for item in complete["files"]:
        check_cancel(cancel)
        if not isinstance(item, dict):
            raise TypeError("period_complete_file_invalid")
        freq, period = item.get("freq"), item.get("period")
        version = item.get("version")
        if (
            freq not in saved["identity"]["intent"]["frequencies"]
            or freq not in ("week", "month")
            or not isinstance(period, str)
            or not isinstance(item.get("target"), str)
            or not isinstance(version, list)
            or len(version) != 5
            or any(type(value) is not int or value < 0 for value in version)
            or type(item.get("rows")) is not int
            or item["rows"] < 0
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise ValueError("period_complete_file_invalid")
        period_date(period, freq)
        if (
            item["target"]
            != str(_target_path(Path(saved["identity"]["root"]), freq, period))
            or (freq, period) in seen
        ):
            raise ValueError("period_complete_file_identity_changed")
        seen.add((freq, period))
    return complete


def require_current_files(complete, *, cancel=lambda: False):
    """A current-file operation must still enforce the original version guard."""
    for item in complete["files"]:
        check_cancel(cancel)
        if file_version(item["target"]) != item["version"]:
            raise ValueError("period_committed_file_changed")


def completed_files(run, saved, *, cancel=lambda: False):
    complete = completed_receipt(run, saved, cancel=cancel)
    require_current_files(complete, cancel=cancel)
    return complete


def history_work_identity(work):
    """The existing five-field identity, independently checked against the queue."""
    if not isinstance(work, dict) or work.get("kind") != "history":
        raise ValueError("period_history_work_invalid")
    try:
        identity = {key: work[key] for key in ("intent", "policy", "root", "listed", "aliases")}
    except KeyError as error:
        raise ValueError("period_history_work_invalid") from error
    if (
        identity["intent"].get("mode") != "history"
        or identity["intent"].get("asof") is not None
        or work.get("identity_hash") != digest(identity)
        or "consumed" in work
    ):
        raise ValueError("period_history_work_invalid")
    return identity


def ensure_history_pending(
    run, *, root, staging, saved=None, identity=None, confirmed_retired=(),
    allowed_frequencies=None, cancel=lambda: False,
):
    """Durably register an explicit manual history, without daily consumption."""
    root, staging = roots(root, staging)
    run = safe_path(Path(run))
    if run != staging / "stock_period/runs" / run.name:
        raise ValueError("period_event_run_path_invalid")
    if saved is not None:
        verify_execution(saved, run.name)
        if identity is not None and saved["identity"] != identity:
            raise ValueError("period_manifest_changed")
        identity = saved["identity"]
    if identity is None:
        raise ValueError("period_history_identity_required")
    intent = identity["intent"]
    if intent.get("mode") != "history" or intent.get("asof") is not None:
        return None
    if identity.get("root") != str(root) or execution_id(intent["request_id"]) != run.name:
        raise ValueError("period_manifest_changed")
    with writer(staging):
        check_cancel(cancel)
        path = staging / "stock_period/daily.json"
        state = read_json(path) if path.exists() else {"pending_work": {}}
        pending = state.setdefault("pending_work", {})
        existing = pending.get(run.name)
        if existing is not None and existing.get("kind") != "history":
            if any(existing.get(key) != identity[key] for key in ("intent", "policy", "listed", "aliases")):
                raise ValueError("period_history_work_invalid")
            return None
        if saved is not None and saved["phase"] == "events_complete" and existing is None:
            completed_receipt(run, saved, cancel=cancel)
            return None
        frequencies = set(intent["frequencies"])
        if saved is not None and saved["phase"] in ("files_complete", "events_complete"):
            frequencies = {item["freq"] for item in completed_receipt(run, saved, cancel=cancel)["files"]}
        if existing is None and allowed_frequencies is not None and not frequencies <= set(allowed_frequencies):
            raise ValueError("period_history_registration_required")
        device_ids = saved["devices"] if saved is not None else devices(root, staging)
        check_devices(root, staging, device_ids)
        started = saved["started_at"] if saved is not None else (
            existing["started_at"] if existing is not None else execution_time()
        )
        try:
            if datetime.fromisoformat(started).tzinfo is None:
                raise ValueError("period_pending_start_invalid")
        except (TypeError, ValueError) as error:
            raise ValueError("period_pending_start_invalid") from error
        work = {
            **identity, "kind": "history", "identity_hash": digest(identity),
            "confirmed_retired": sorted(confirmed_retired),
            "devices": device_ids, "started_at": started,
        }
        if existing is not None:
            history_work_identity(existing)
            if saved is not None and not confirmed_retired:
                work["confirmed_retired"] = existing["confirmed_retired"]
            if existing != work:
                raise ValueError("period_history_work_changed")
            return existing
        pending[run.name] = work
        atomic_json(path, state)
        return work


def frozen_history_work(root, staging, intent):
    """Only this explicit request; never search other executions or today's pool."""
    root, staging = roots(root, staging)
    run = staging / "stock_period/runs" / execution_id(intent["request_id"])
    path = staging / "stock_period/daily.json"
    work = (read_json(path).get("pending_work", {}).get(run.name) if path.exists() else None)
    manifest = run / "manifest.json"
    saved = read_json(manifest) if manifest.exists() else None
    if saved is not None:
        verify_execution(saved, run.name)
        identity = saved["identity"]
    elif work is not None:
        identity = history_work_identity(work)
    else:
        return None
    if identity["intent"] != intent or identity["root"] != str(root):
        raise ValueError("period_manifest_changed")
    if work is not None and work.get("kind") == "history" and history_work_identity(work) != identity:
        raise ValueError("period_history_work_changed")
    return identity


def ordered_pending_work(staging, state=None):
    """Order shared intents by their frozen business date and actual start."""
    control = Path(staging) / "stock_period"
    if state is None:
        path = control / "daily.json"
        state = read_json(path) if path.exists() else {}
    pending = state.get("pending_work", {})
    if not isinstance(pending, dict):
        raise TypeError("period_pending_work_invalid")
    ordered = []
    for run_id, work in pending.items():
        if (
            not isinstance(work, dict)
            or not isinstance(work.get("intent"), dict)
            or run_id != execution_id(work["intent"].get("request_id"))
        ):
            raise ValueError("period_pending_work_invalid")
        manifest = control / "runs" / run_id / "manifest.json"
        started = None
        history_identity = history_work_identity(work) if work.get("kind") == "history" else None
        if history_identity is not None:
            try:
                started = datetime.fromisoformat(work["started_at"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("period_pending_start_invalid") from error
            if started.tzinfo is None:
                raise ValueError("period_pending_start_invalid")
        if manifest.exists():
            saved = read_json(manifest)
            verify_execution(saved, run_id)
            if history_identity is not None and (
                saved["identity"] != history_identity
                or saved["started_at"] != work["started_at"]
                or saved["devices"] != work["devices"]
            ):
                raise ValueError("period_history_work_changed")
            try:
                started = datetime.fromisoformat(saved["started_at"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("period_pending_start_invalid") from error
            if started.tzinfo is None:
                raise ValueError("period_pending_start_invalid")
        asof = work["intent"].get("asof")
        if asof is not None:
            try:
                normalized = date.fromisoformat(asof).isoformat()
            except (TypeError, ValueError) as error:
                raise ValueError("period_pending_date_invalid") from error
            if normalized != asof:
                raise ValueError("period_pending_date_invalid")
        elif started is not None:
            asof = started.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        else:
            raise ValueError("period_pending_date_missing")
        ordered.append(
            (
                (asof, started is None, started.timestamp() if started else 0, run_id),
                work,
            )
        )
    return [work for _, work in sorted(ordered, key=lambda entry: entry[0])]


def require_pending_delivery_before_write(
    staging, run_id, *, root, confirm_delivery=None, cancel=lambda: False
):
    """All writers must finish earlier delivery work before a new intent writes."""
    for work in ordered_pending_work(staging):
        check_cancel(cancel)
        pending_id = execution_id(work["intent"]["request_id"])
        if pending_id == run_id:
            return
        pending_run = Path(staging) / "stock_period/runs" / pending_id
        manifest = pending_run / "manifest.json"
        if (
            confirm_delivery is None
            or not manifest.exists()
            or read_json(manifest).get("phase")
            not in ("files_complete", "events_complete")
        ):
            raise ValueError(f"period_original_run_required:{pending_id}")
        confirmation = confirm_delivery(pending_run)
        if not isinstance(confirmation, dict) or confirmation.get("events_complete") is not True:
            raise ValueError(f"period_original_run_required:{pending_id}")
        from orchestrator.defs.stock_period_update import acknowledge_period_delivery

        acknowledge_period_delivery(
            pending_run,
            confirmation,
            root=root,
            staging=staging,
            cancel=cancel,
        )
        path = Path(staging) / "stock_period/daily.json"
        if pending_id in read_json(path).get("pending_work", {}):
            raise ValueError(f"period_original_run_required:{pending_id}")


def validate_registered_targets(items, *, run, saved, baseline, cancel=lambda: False):
    """Current stat is a preimage only after its owner is independently known."""
    facts = read_json(baseline)
    registered = {}
    duplicates = set()
    for item in facts.get("files", []):
        target = item["target"]
        if target in registered:
            duplicates.add(target)
        registered[target] = item
    candidate_groups = {}

    def candidates_for(freq):
        path = run / (freq + ".candidates.json")
        cached = candidate_groups.get(freq)
        if cached is not None:
            if file_version(path) != cached["version"]:
                raise ValueError("period_target_commit_ownership_invalid")
            return cached["items"]
        before = file_version(path)
        candidates = read_json(path)
        if (
            file_version(path) != before
            or not isinstance(candidates, list)
            or any(not isinstance(candidate, dict) for candidate in candidates)
            or saved.get("candidate_hashes", {}).get(freq) != digest(candidates)
        ):
            raise ValueError("period_target_commit_ownership_invalid")
        indexed = {}
        for candidate in candidates:
            if candidate.get("freq") != freq:
                raise ValueError("period_target_commit_ownership_invalid")
            key = (candidate.get("period"), candidate.get("target"))
            indexed.setdefault(key, []).append(candidate)
        candidate_groups[freq] = {"version": before, "items": indexed}
        return indexed

    for item in items:
        check_cancel(cancel)
        target, version = item["target"], item["version"]
        if target in duplicates:
            raise ValueError("period_target_registration_invalid")
        prior = registered.get(target)
        cp = run / "committed" / item["freq"] / (item["period"] + ".json")
        committed = None
        if cp.exists():
            committed = read_json(cp)
            matches = candidates_for(item["freq"]).get((item["period"], target), [])
            if (
                len(matches) != 1
                or any(
                    committed.get(key) != matches[0].get(key)
                    for key in (
                        "candidate",
                        "freq",
                        "period",
                        "target",
                        "target_preimage",
                        "rows",
                        "sha256",
                    )
                )
                or committed.get("version") != version
                or version[:4] != matches[0]["version"][:4]
            ):
                raise ValueError("period_target_commit_ownership_invalid")
        if committed is not None:
            if item["target_preimage"] not in (
                committed["target_preimage"],
                committed["version"],
            ):
                raise ValueError("period_target_preimage_changed")
            continue
        if version is None:
            if prior is not None:
                raise ValueError("period_registered_target_missing")
        elif (
            prior is None
            or prior.get("freq") != item["freq"]
            or prior.get("period") != item["period"]
            or prior.get("version") != version
        ):
            raise ValueError("period_target_unregistered_version")
        if item["target_preimage"] != version:
            raise ValueError("period_target_preimage_changed")


def recover_moved_candidate(run, saved, freq, candidates, baseline, cancel):
    """Restore only the single interrupted rename using the original publisher."""
    from orchestrator.defs.io.stock_period_raw import target_path

    moved = []
    seen = set()
    for item in candidates:
        check_cancel(cancel)
        key = (item["freq"], item["period"])
        candidate = safe_path(Path(item["candidate"]))
        if (
            key in seen or item["freq"] != freq
            or item["target"] != str(target_path(Path(saved["identity"]["root"]), freq, item["period"]))
            or not candidate.is_relative_to(run / "build" / freq)
            or "target_preimage" not in item
        ):
            raise ValueError("period_candidate_manifest_changed")
        seen.add(key)
        cp = run / "committed" / freq / (item["period"] + ".json")
        if not cp.exists() and not candidate.exists():
            moved.append((item, cp))
    if len(moved) > 1:
        raise ValueError("period_multiple_unrecorded_promotions")
    for item, cp in moved:
        facts = read_json(baseline)
        previous = [entry for entry in facts.get("files", []) if entry["target"] == item["target"]]
        expected = previous[0]["version"] if len(previous) == 1 else None
        if len(previous) > 1 or item["target_preimage"] != expected:
            raise ValueError("period_target_preimage_changed")
        if (
            not Path(item["target"]).exists()
            or file_version(item["target"])[:4] != item["version"][:4]
        ):
            raise ValueError("period_target_unregistered_version")
        publish(item, checkpoint=cp, cancel=cancel)


def replay_events(
    run,
    *,
    root,
    staging,
    events=None,
    completion_events=None,
    confirm_delivery=None,
    allowed_frequencies=None,
    cancel=lambda: False,
):
    """Event-only reader: no source, SQL, candidate assembly or file replacement."""
    root, staging = roots(root, staging)
    with writer(staging):
        run = safe_path(run)
        if run != staging / "stock_period/runs" / run.name:
            raise ValueError("period_event_run_path_invalid")
        saved = read_json(run / "manifest.json")
        verify_execution(saved, run.name)
        if saved["identity"]["root"] != str(root) or saved["phase"] not in (
            "files_complete",
            "events_complete",
        ):
            raise ValueError("period_event_files_incomplete")
        check_devices(root, staging, saved["devices"])
        complete = completed_receipt(run, saved, cancel=cancel)
        frequencies = {item["freq"] for item in complete["files"]}
        if allowed_frequencies is not None and (
            not isinstance(allowed_frequencies, (list, tuple, set))
            or not set(allowed_frequencies) <= {"week", "month"}
            or not set(allowed_frequencies) & frequencies
        ):
            raise ValueError("period_delivery_frequency_scope_invalid")
        ensure_history_pending(
            run, root=root, staging=staging, saved=saved,
            allowed_frequencies=allowed_frequencies, cancel=cancel,
        )
        from orchestrator.defs.run_contracts.stock_period import (
            completion_notice,
            completion_reference,
        )

        notices = {
            freq: completion_notice(
                completion_reference(run.name, saved["file_receipt_hash"], freq),
                freq,
                sum(i["freq"] == freq for i in complete["files"]),
            )
            for freq in sorted({i["freq"] for i in complete["files"]})
        }
        confirmation = None
        allowed = set(notices) if allowed_frequencies is None else set(allowed_frequencies) & set(notices)

        def confirm():
            proof = confirm_delivery(run)
            if (
                not isinstance(proof, dict)
                or proof.get("run_id") != complete["run_id"]
                or proof.get("identity_hash") != saved["identity_hash"]
                or proof.get("file_receipt_hash") != saved["file_receipt_hash"]
                or proof.get("files") != complete["files"]
                or type(proof.get("events_complete")) is not bool
                or type(proof.get("allowed_events_complete")) is not bool
            ):
                raise ValueError("period_delivery_confirmation_invalid")
            if not proof["allowed_events_complete"] and proof.get("reason") not in (
                "missing_events",
                "missing_checks",
                "current_events_incomplete",
            ):
                raise ValueError("period_delivery_confirmation_incomplete")
            scope = proof.get("allowed_frequencies")
            if (
                not isinstance(scope, (list, tuple, set))
                or not set(scope).issubset({"week", "month"})
                or not set(scope) & set(notices)
                or (allowed_frequencies is not None and not set(scope) <= set(allowed_frequencies))
            ):
                raise ValueError("period_delivery_frequency_scope_invalid")
            if proof["events_complete"] != (
                proof["allowed_events_complete"] and set(notices) <= set(scope)
            ):
                raise ValueError("period_delivery_confirmation_invalid")
            return proof, set(scope) & set(notices)

        def confirmed_result(proof):
            from orchestrator.defs.stock_period_update import (
                acknowledge_period_delivery,
            )

            acknowledge_period_delivery(
                run, proof, root=root, staging=staging, cancel=cancel
            )
            return {
                **complete,
                "path": str(run),
                "events_complete": proof["events_complete"],
                "allowed_events_complete": proof["allowed_events_complete"],
                "historical_only": proof.get("historical_only", False),
                "current_files": proof.get("current_files", []),
                "completions": {freq: notice for freq, notice in notices.items()
                                if freq in proof["allowed_frequencies"]},
                "confirmation": proof,
            }

        if confirm_delivery is not None:
            confirmation, allowed = confirm()
            if confirmation["allowed_events_complete"]:
                return confirmed_result(confirmation)
        current_files = (
            confirmation["current_files"] if confirmation is not None
            else [item for item in complete["files"] if item["freq"] in allowed]
        )
        if not isinstance(current_files, list):
            raise TypeError("period_delivery_confirmation_invalid")
        frozen_files = {(item["freq"], item["period"]): item for item in complete["files"]}
        current_keys = set()
        for item in current_files:
            if not isinstance(item, dict):
                raise TypeError("period_delivery_confirmation_invalid")
            key = (item.get("freq"), item.get("period"))
            if key in current_keys or item.get("freq") not in allowed or frozen_files.get(key) != item:
                raise ValueError("period_delivery_confirmation_invalid")
            current_keys.add(key)
        require_current_files(
            {"files": current_files},
            cancel=cancel,
        )
        pending = False
        from orchestrator.defs.io.stock_period_raw import _AUDIT_LOCK, _AUDITS

        for item in complete["files"]:
            check_cancel(cancel)
            if item["freq"] not in allowed:
                pending = True
                continue
            if confirmation is not None:
                if (item["freq"], item["period"]) not in current_keys:
                    continue
                from orchestrator.defs.stock_period_update import (
                    _period_delivery_file_proven,
                )

                evidence = confirmation.get("file_evidence", {}).get((item["freq"], item["period"]))
                if _period_delivery_file_proven(evidence, item):
                    continue
            cp = run / "events" / item["freq"] / (item["period"] + ".json")
            expected = {k: item[k] for k in ("version", "sha256")}
            if cp.exists():
                if read_json(cp) != expected:
                    raise ValueError("period_event_checkpoint_changed")
                if confirmation is None:
                    continue
            # The complete receipt is frozen and the exact file version is verified above.
            with _AUDIT_LOCK:
                if len(_AUDITS) >= 4096:
                    _AUDITS.pop(next(iter(_AUDITS)))
                _AUDITS[(item["target"], tuple(item["version"]))] = {
                    k: item[k] for k in ("rows", "version", "sha256")
                }
            if (
                events is None
                or events(item, completion=notices[item["freq"]]) is not True
            ):
                pending = True
                continue
            if confirmation is None:
                atomic_json(cp, expected)
        for freq, notice in notices.items():
            check_cancel(cancel)
            if freq not in allowed:
                pending = True
                continue
            if confirmation is not None and freq in confirmation.get("completion_evidence", {}):
                continue
            cp = run / "events/completion" / (freq + ".json")
            if cp.exists():
                receipt = read_json(cp)
                if (
                    receipt.get("completion") != notice
                    or type(receipt.get("observation_id")) is not int
                    or receipt["observation_id"] <= 0
                ):
                    raise ValueError("period_completion_checkpoint_changed")
                continue
            observation_id = (
                completion_events(notice) if completion_events is not None else None
            )
            if type(observation_id) is not int or observation_id <= 0:
                pending = True
            elif confirmation is None:
                atomic_json(
                    cp, {"completion": notice, "observation_id": observation_id}
                )
        if confirm_delivery is not None:
            confirmation, allowed = confirm()
            if confirmation["allowed_events_complete"]:
                return confirmed_result(confirmation)
            pending = True
            return {
                **complete, "path": str(run), "events_complete": False,
                "allowed_events_complete": False,
                "historical_only": confirmation["historical_only"],
                "current_files": confirmation["current_files"],
                "completions": {freq: notices[freq] for freq in allowed},
                "confirmation": confirmation,
            }
        phase = "files_complete" if pending else "events_complete"
        if allowed != set(notices) and saved["phase"] == "events_complete":
            phase = saved["phase"]
        if saved["phase"] != phase:
            saved["phase"] = phase
            atomic_json(run / "manifest.json", saved)
        return {
            **complete,
            "path": str(run),
            "events_complete": not pending,
            "historical_only": False,
            "current_files": [i for i in complete["files"] if i["freq"] in allowed],
            "completions": notices,
            **({"confirmation": confirmation} if confirmation is not None else {}),
        }


def _finish_files(run, saved, baseline, intent, changed):
    complete = {
        "run_id": run.name,
        "files": changed,
        "unit_asofs": saved.get("unit_asofs", {}),
    }
    atomic_json(run / "complete.json", complete)
    saved.update(
        phase="files_complete",
        file_receipt_hash=digest(complete),
        files_completed_at=execution_time(),
    )
    atomic_json(run / "manifest.json", saved)
    _record_ranges(baseline, run, intent, changed)
    if intent["mode"] == "bootstrap":
        facts = read_json(baseline)
        facts.update(
            status="files_ready", run_id=run.name, listed=saved["identity"]["listed"]
        )
        atomic_json(baseline, facts)
    saved["ranges_recorded"] = True
    atomic_json(run / "manifest.json", saved)


def verify_rss_resume(staging, run_id, identity):
    """Allow exact recorded daily work or an existing bootstrap/handoff."""
    manifest_path = safe_path(staging / "stock_period/runs" / run_id / "manifest.json")
    intent = identity["intent"]
    if (
        intent["mode"] != "bootstrap"
        and intent.get("asof") is not None
        and "bootstrap_parent" not in intent
    ):
        daily_path = safe_path(staging / "stock_period/daily.json")
        work = (
            read_json(daily_path).get("pending_work", {}).get(run_id)
            if daily_path.is_file()
            else None
        )
        try:
            asof = date.fromisoformat(intent["asof"]).isoformat()
        except (TypeError, ValueError):
            raise ValueError("period_runtime_rss_daily_invalid") from None
        if (
            intent.get("mode") not in ("upsert", "history")
            or asof != intent["asof"]
            or not isinstance(work, dict)
            or work.get("kind") is not None
            or work.get("frequency") not in ("week", "month")
            or not isinstance(work.get("listed"), list)
            or not isinstance(work.get("aliases"), dict)
            or not isinstance(work.get("policy"), dict)
            or intent.get("request_id")
            != digest(
                {"kind": "period_daily", "frequency": work["frequency"], "date": asof}
            )
            or run_id != execution_id(intent["request_id"])
            or identity
            != {
                "intent": work.get("intent"),
                "policy": work["policy"],
                "root": identity["root"],
                "listed": sorted(work["listed"]),
                "aliases": work["aliases"],
            }
        ):
            raise ValueError("period_runtime_rss_daily_invalid")
        if manifest_path.is_file():
            saved = read_json(manifest_path)
            verify_execution(saved, run_id)
            if saved["identity"] != identity:
                raise ValueError("period_manifest_changed")
        return
    if not manifest_path.is_file():
        raise ValueError("period_runtime_rss_resume_required")
    if intent["mode"] == "bootstrap":
        return
    parent_id = intent.get("bootstrap_parent")
    if (
        intent["mode"] != "upsert"
        or not isinstance(parent_id, str)
        or not re.fullmatch(r"[0-9a-f]{64}", parent_id)
    ):
        raise ValueError("period_runtime_rss_handoff_invalid")
    parent_path = safe_path(staging / "stock_period/runs" / parent_id / "manifest.json")
    if not parent_path.is_file():
        raise ValueError("period_runtime_rss_handoff_invalid")
    parent = read_json(parent_path)
    verify_execution(parent, parent_id)
    baseline = read_json(safe_path(staging / "stock_period/baseline.json"))
    work = parent.get("handoff", {})
    if (
        parent["identity"]["intent"]["mode"] != "bootstrap"
        or parent["phase"] != "events_complete"
        or parent["identity"]["root"] != identity["root"]
        or parent["identity"]["policy"] != identity["policy"]
        or work.get("intent") != intent
        or work.get("listed") != identity["listed"]
        or work.get("aliases") != identity["aliases"]
        or baseline.get("run_id") != parent_id
        or baseline.get("status") not in ("files_ready", "ready")
    ):
        raise ValueError("period_runtime_rss_handoff_invalid")


def run_period(
    *,
    root,
    staging,
    intent,
    listed,
    aliases,
    confirmed_retired=(),
    transport=None,
    policy=DEFAULT_POLICY,
    runtime_rss_bytes=None,
    cancel=lambda: False,
    progress=lambda _: None,
    events=None,
    completion_events=None,
    confirm_delivery=None,
):
    """No formal operation is invoked by import. All tests supply explicit temporary roots."""
    if runtime_rss_bytes is not None and (
        type(runtime_rss_bytes) is not int or runtime_rss_bytes <= 0
    ):
        raise ValueError("period_runtime_rss_limit_invalid")
    root, staging = roots(root, staging)
    initial_devices = devices(root, staging)
    if initial_devices["root"] != initial_devices["staging"]:
        raise ValueError("period_atomic_device_mismatch")
    if intent.get("version") != VERSION or intent.get("mode") not in (
        "bootstrap",
        "upsert",
        "history",
    ):
        raise ValueError("period_intent_version_or_mode_invalid")
    if not listed and intent["mode"] == "bootstrap":
        raise ValueError("period_listed_scope_empty")
    mode = intent["mode"]
    freqs = intent["frequencies"]
    if (
        not freqs
        or len(set(freqs)) != len(freqs)
        or not set(freqs) <= {"week", "month"}
    ):
        raise ValueError("period_intent_frequency_invalid")
    codes = sorted(set(intent.get("codes", [])))
    retiring = sorted(set(intent.get("retired_codes", [])))
    superseded = sorted(set(intent.get("superseded_codes", [])))
    if any(
        c in listed or aliases.get(c, c) == c or aliases.get(c) not in listed
        for c in superseded
    ):
        raise ValueError("period_code_replacement_not_confirmed")
    if not set(retiring).issubset(set(confirmed_retired)) or set(retiring) & set(
        listed
    ):
        raise ValueError("period_retirement_not_confirmed")
    if mode in ("bootstrap", "history") or codes:
        if not codes and not (mode == "history" and (retiring or superseded)):
            raise ValueError("period_intent_codes_empty")
        for code in codes:
            admitted_code(code, listed, aliases)
    if mode == "bootstrap" and (
        set(freqs) != {"week", "month"} or set(codes) != set(listed)
    ):
        raise ValueError("period_bootstrap_scope_incomplete")
    identity = {
        "intent": intent,
        "policy": policy.payload(),
        "root": str(root),
        "listed": sorted(listed),
        "aliases": aliases,
    }
    run_id = execution_id(intent.get("request_id"))
    if runtime_rss_bytes is not None:
        verify_rss_resume(staging, run_id, identity)
    with (
        writer(staging) as control,
        process_memory_budget(policy, runtime_rss_bytes, progress=progress),
    ):
        run = safe_path(control / "runs" / run_id)
        manifest = run / "manifest.json"
        prior = None
        history_work = None
        manual_history = mode == "history" and intent.get("asof") is None
        if manifest.exists():
            prior = read_json(manifest)
            verify_execution(prior, run_id)
            if prior["identity"] != identity:
                raise ValueError("period_manifest_changed")
            if manual_history:
                history_work = ensure_history_pending(
                    run, root=root, staging=staging, saved=prior,
                    confirmed_retired=confirmed_retired, cancel=cancel,
                )
                if prior["phase"] != "events_complete":
                    require_pending_delivery_before_write(
                        staging, run_id, root=root,
                        confirm_delivery=confirm_delivery, cancel=cancel,
                    )
            if prior["phase"] in ("files_complete", "events_complete"):
                check_devices(root, staging, prior["devices"])
                if not prior.get("ranges_recorded"):
                    if confirm_delivery is not None:
                        proof = confirm_delivery(run)
                        if isinstance(proof, dict) and proof.get("historical_only"):
                            raise ValueError("period_historical_range_record_required")
                    complete = completed_files(run, prior, cancel=cancel)
                    _record_ranges(
                        control / "baseline.json", run, intent, complete["files"]
                    )
                    if mode == "bootstrap":
                        facts = read_json(control / "baseline.json")
                        facts.update(
                            status="files_ready", run_id=run_id, listed=sorted(listed)
                        )
                        atomic_json(control / "baseline.json", facts)
                    prior["ranges_recorded"] = True
                    atomic_json(manifest, prior)
                return replay_events(
                    run,
                    root=root,
                    staging=staging,
                    events=events,
                    completion_events=completion_events,
                    confirm_delivery=confirm_delivery,
                    cancel=cancel,
                )
        if manual_history and (
            not (control / "baseline.json").exists()
            or read_json(control / "baseline.json").get("status") != "ready"
        ):
            raise ValueError("period_baseline_not_ready")
        require_pending_delivery_before_write(
            staging,
            run_id,
            root=root,
            confirm_delivery=confirm_delivery,
            cancel=cancel,
        )
        if manual_history:
            history_work = ensure_history_pending(
                run, root=root, staging=staging, saved=prior, identity=identity,
                confirmed_retired=confirmed_retired, cancel=cancel,
            )
        run.mkdir(parents=True, exist_ok=True)
        budget = StorageBudget(run, policy, cancel=cancel, progress=progress)
        budget_token = _BUDGET.set(budget)
        try:
            manifest = run / "manifest.json"
            if manifest.exists():
                saved = read_json(manifest)
                verify_execution(saved, run_id)
                if saved["identity"] != identity:
                    raise ValueError("period_manifest_changed")
            else:
                # Reserve actual next writes, not the entire configured workspace ceiling.
                budget.reserve(2 * policy.response_bytes)
                saved = {
                    "identity": identity,
                    "identity_hash": digest(identity),
                    "phase": "deleting" if mode == "bootstrap" else "download",
                    "devices": devices(root, staging),
                    "started_at": history_work["started_at"] if history_work is not None else execution_time(),
                }
                atomic_json(manifest, saved)
            check_devices(root, staging, saved["devices"])
            budget.guard = lambda: check_devices(root, staging, saved["devices"])
            baseline = control / "baseline.json"
            if mode != "bootstrap" and (
                not baseline.exists()
                or (
                    read_json(baseline).get("status") != "ready"
                    and not (
                        intent.get("bootstrap_parent")
                        == read_json(baseline).get("run_id")
                        and read_json(baseline).get("status") == "files_ready"
                    )
                )
            ):
                raise ValueError("period_baseline_not_ready")
            if mode == "bootstrap" and baseline.exists():
                active = read_json(baseline)
                if (
                    active.get("status") in ("rebuilding", "files_ready")
                    and active.get("run_id") != run_id
                ):
                    raise ValueError("period_other_bootstrap_incomplete")
            if mode == "bootstrap" and saved["phase"] == "deleting":
                if root.exists():
                    sync_directory(root)
                atomic_json(baseline, {"status": "rebuilding", "run_id": run_id})
                for freq in freqs:
                    check_devices(root, staging, saved["devices"])
                    remove_dataset(root, freq, cancel)
                saved["phase"] = "download"
                atomic_json(manifest, saved)
            awaiting = saved.pop("awaiting_units", [])
            for key in awaiting:
                saved.setdefault("capture_rounds", {})[key] = (
                    saved.get("capture_rounds", {}).get(key, 0) + 1
                )
            if awaiting:
                atomic_json(manifest, saved)
            changed = []
            prepared = []
            cached = {}
            unrecorded = 0
            for freq in freqs:
                path = run / f"{freq}.candidates.json"
                if not path.exists():
                    continue
                candidates = read_json(path)
                if saved.get("candidate_hashes", {}).get(freq) != digest(candidates):
                    raise ValueError("period_candidate_manifest_changed")
                cached[freq] = candidates
                for item in candidates:
                    check_cancel(cancel)
                    if (
                        not (run / "committed" / freq / (item["period"] + ".json")).exists()
                        and not safe_path(Path(item["candidate"])).exists()
                    ):
                        unrecorded += 1
            if unrecorded > 1:
                raise ValueError("period_multiple_unrecorded_promotions")
            for freq in freqs:
                candidates_file = run / f"{freq}.candidates.json"
                if freq in cached:
                    candidates = cached[freq]
                    recover_moved_candidate(run, saved, freq, candidates, baseline, cancel)
                    validate_registered_targets(
                        [
                            {
                                "freq": item["freq"],
                                "period": item["period"],
                                "target": item["target"],
                                "version": file_version(item["target"])
                                if Path(item["target"]).exists()
                                else None,
                                "target_preimage": item["target_preimage"],
                            }
                            for item in candidates
                        ],
                        run=run,
                        saved=saved,
                        baseline=baseline,
                        cancel=cancel,
                    )
                else:
                    units = []
                    used = 0
                    scope = [(code, None) for code in codes]
                    if mode == "upsert":
                        scope = [
                            (None, period)
                            for period in intent.get("periods", {}).get(freq, ())
                        ] + scope
                    for index, (code, period) in enumerate(scope):
                        check_cancel(cancel)
                        _rss(policy)
                        transport = transport or HttpPage(
                            policy=policy, cancel=cancel, progress=progress
                        )
                        captured = capture_unit(
                            work=run / "source",
                            request_id=intent["request_id"]
                            if not saved.get("capture_rounds", {}).get(
                                freq + ":" + str(period)
                            )
                            else digest(
                                {
                                    "intent": intent["request_id"],
                                    "unit": [freq, period],
                                    "round": saved["capture_rounds"][
                                        freq + ":" + str(period)
                                    ],
                                }
                            ),
                            freq=freq,
                            listed=listed,
                            aliases=aliases,
                            code=code,
                            period=period,
                            transport=transport,
                            policy=policy,
                            cancel=cancel,
                            progress=progress,
                        )
                        units.append(captured)
                        used += sum(
                            p["bytes"] + p["csv_version"][2] for p in captured["pages"]
                        )
                        progress(
                            {
                                "stage": "source_unit_complete",
                                "freq": freq,
                                "completed": index + 1,
                                "total": len(scope),
                            }
                        )
                    stale = [
                        freq + ":" + str(u["identity"]["period"])
                        for u in units
                        if u["identity"]["period"]
                        and intent.get("asof")
                        and (
                            not u["maximum_asof"]
                            or u["maximum_asof"]
                            < intent.get("period_cutoffs", {})
                            .get(freq, {})
                            .get(
                                u["identity"]["period"],
                                min(
                                    intent["asof"].replace("-", ""),
                                    period_date(u["identity"]["period"], freq),
                                ),
                            )
                        )
                    ]
                    if stale:
                        saved["awaiting_units"] = stale
                        atomic_json(manifest, saved)
                        raise ValueError("period_source_not_published")
                    paths = [p["csv"] for u in units for p in u["pages"]]
                    build = run / "build" / freq
                    # An interrupted COPY has no complete manifest; only its private disposable candidates rebuild.
                    if build.exists() and not (build / "copy.json").exists():
                        safe_path(build)
                        shutil.rmtree(build)
                        budget.forget_tree(build)
                    candidates = assemble(
                        paths,
                        work=build,
                        root=root,
                        mode=mode,
                        freq=freq,
                        codes=codes,
                        retired_codes=sorted(set(retiring) | set(superseded)),
                        periods=intent.get("periods", {}).get(freq, ()),
                        history_sources=[
                            p["csv"]
                            for u in units
                            if u["identity"]["code"] is not None
                            for p in u["pages"]
                        ],
                        range_evidence=read_json(baseline),
                        policy=policy,
                        cancel=cancel,
                        progress=progress,
                        validate_targets=lambda items: validate_registered_targets(
                            items,
                            run=run,
                            saved=saved,
                            baseline=baseline,
                            cancel=cancel,
                        ),
                    )
                    candidate_bytes = sum(i["version"][2] for i in candidates)
                    saved.setdefault("unit_asofs", {})[freq] = {
                        str(u["identity"]["period"] or u["identity"]["code"]): u[
                            "maximum_asof"
                        ]
                        for u in units
                    }
                    saved.setdefault("source_bytes", {})[freq] = used
                    saved.setdefault("candidate_bytes", {})[freq] = candidate_bytes
                    asofs = [u["maximum_asof"] for u in units]
                    saved.setdefault("source_asof", {})[freq] = (
                        min(asofs) if asofs and all(asofs) else None
                    )
                    saved.setdefault("candidate_hashes", {})[freq] = digest(candidates)
                    atomic_json(manifest, saved)
                    atomic_json(candidates_file, candidates)
                prepared.append((freq, candidates))
            # No file is published until every source/candidate in this intent has succeeded.
            for freq, candidates in prepared:
                for index, item in enumerate(candidates):
                    check_cancel(cancel)
                    cp = run / "committed" / freq / f"{item['period']}.json"
                    check_devices(root, staging, saved["devices"])
                    budget.reserve(device=target_parent(item["target"]))
                    result = publish(item, checkpoint=cp, cancel=cancel)
                    changed.append(result)
                    progress(
                        {
                            "stage": "file_committed",
                            "freq": freq,
                            "completed": index + 1,
                            "total": len(candidates),
                        }
                    )
            _finish_files(run, saved, baseline, intent, changed)
            if events is None and confirm_delivery is not None:
                # A new file phase has no native results yet. The daily caller
                # consumes these frozen facts before its one event replay.
                from orchestrator.defs.run_contracts.stock_period import (
                    completion_notice,
                    completion_reference,
                )

                complete = completed_receipt(run, saved, cancel=cancel)
                notices = {
                    freq: completion_notice(
                        completion_reference(
                            run.name, saved["file_receipt_hash"], freq
                        ),
                        freq,
                        sum(item["freq"] == freq for item in complete["files"]),
                    )
                    for freq in sorted({item["freq"] for item in complete["files"]})
                }
                return {
                    **complete,
                    "path": str(run),
                    "events_complete": False,
                    "historical_only": False,
                    "current_files": complete["files"],
                    "completions": notices,
                }
            return replay_events(
                run,
                root=root,
                staging=staging,
                events=events,
                completion_events=completion_events,
                confirm_delivery=confirm_delivery,
                cancel=cancel,
            )
        finally:
            _BUDGET.reset(budget_token)
