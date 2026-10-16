"""Period Raw coordinator: fixed-root reset, capture, columnar build, commit and event resume."""

from __future__ import annotations

import fcntl
import os
import shutil
import signal
import threading
from contextlib import contextmanager
from datetime import datetime
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
    if intent["mode"] == "bootstrap":
        facts["stock_ranges"] = {}
        facts["files"] = []
        facts["range_index_version"] = VERSION
    for freq in intent["frequencies"]:
        copied = read_json(run / "build" / freq / "copy.json")
        incoming = copied["stock_ranges"]
        if not copied["range_index_valid"]:
            facts.pop("range_index_version", None)
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
    facts["range_index_hash"] = digest({k: facts[k] for k in ("files", "stock_ranges")})
    atomic_json(baseline, facts)


def target_parent(path):
    parent = Path(path).parent
    while not parent.exists():
        parent = parent.parent
    return parent


def execution_time():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def completed_files(run, saved, *, cancel=lambda: False):
    complete = read_json(run / "complete.json")
    if complete.get("run_id") != execution_id(
        saved["identity"]["intent"]["request_id"]
    ) or saved.get("file_receipt_hash") != digest(complete):
        raise ValueError("period_complete_receipt_changed")
    for item in complete["files"]:
        check_cancel(cancel)
        if file_version(item["target"]) != item["version"]:
            raise ValueError("period_committed_file_changed")
    return complete


def replay_events(run, *, root, staging, events=None, cancel=lambda: False):
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
        complete = completed_files(run, saved, cancel=cancel)
        pending = False
        from orchestrator.defs.io.stock_period_raw import _AUDIT_LOCK, _AUDITS

        for item in complete["files"]:
            check_cancel(cancel)
            cp = run / "events" / item["freq"] / (item["period"] + ".json")
            expected = {k: item[k] for k in ("version", "sha256")}
            if cp.exists():
                if read_json(cp) != expected:
                    raise ValueError("period_event_checkpoint_changed")
                continue
            # The complete receipt is frozen and the exact file version is verified above.
            with _AUDIT_LOCK:
                if len(_AUDITS) >= 4096:
                    _AUDITS.pop(next(iter(_AUDITS)))
                _AUDITS[(item["target"], tuple(item["version"]))] = {
                    k: item[k] for k in ("rows", "version", "sha256")
                }
            if events is None or events(item) is not True:
                pending = True
                continue
            atomic_json(cp, expected)
        phase = "files_complete" if pending else "events_complete"
        if saved["phase"] != phase:
            saved["phase"] = phase
            atomic_json(run / "manifest.json", saved)
        return {**complete, "path": str(run), "events_complete": not pending}


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
    if runtime_rss_bytes is not None and (
        mode != "bootstrap"
        or not safe_path(
            staging / "stock_period/runs" / run_id / "manifest.json"
        ).is_file()
    ):
        raise ValueError("period_runtime_rss_resume_required")
    with (
        writer(staging) as control,
        process_memory_budget(policy, runtime_rss_bytes, progress=progress),
    ):
        run = safe_path(control / "runs" / run_id)
        run.mkdir(parents=True, exist_ok=True)
        manifest = run / "manifest.json"
        if manifest.exists():
            prior = read_json(manifest)
            verify_execution(prior, run_id)
            if prior["identity"] != identity:
                raise ValueError("period_manifest_changed")
            if prior["phase"] in ("files_complete", "events_complete"):
                check_devices(root, staging, prior["devices"])
                if not prior.get("ranges_recorded"):
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
                    run, root=root, staging=staging, events=events, cancel=cancel
                )
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
                    "started_at": execution_time(),
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
            for freq in freqs:
                candidates_file = run / f"{freq}.candidates.json"
                if candidates_file.exists():
                    candidates = read_json(candidates_file)
                    if saved.get("candidate_hashes", {}).get(freq) != digest(
                        candidates
                    ):
                        raise ValueError("period_candidate_manifest_changed")
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
            return replay_events(
                run, root=root, staging=staging, events=events, cancel=cancel
            )
        finally:
            _BUDGET.reset(budget_token)
