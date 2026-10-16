"""Period Raw coordinator: fixed-root reset, capture, columnar build, commit and event resume."""

from __future__ import annotations

import fcntl
import os
import resource
import shutil
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from orchestrator.defs.io.stock_period_raw import (
    assemble,
    atomic_json,
    check_cancel,
    connection,
    dataset_root,
    merge_ranges,
    publish,
    read_json,
    safe_path,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    VERSION,
    admitted_code,
    digest,
    execution_id,
    verify_execution,
)
from orchestrator.defs.stock_period_source import HttpPage, capture_unit


def roots(root, staging):
    root = safe_path(root)
    staging = safe_path(staging)
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


def _rss(policy):
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    if peak > policy.rss_bytes:
        raise ValueError("period_process_memory_exceeded")


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
        for code in intent.get("retired_codes", []):
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
    cancel=lambda: False,
    progress=lambda _: None,
    events=None,
):
    """No formal operation is invoked by import. All tests supply explicit temporary roots."""
    root, staging = roots(root, staging)
    if intent.get("version") != VERSION or intent.get("mode") not in (
        "bootstrap",
        "upsert",
        "history",
    ):
        raise ValueError("period_intent_version_or_mode_invalid")
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
    if not set(retiring).issubset(set(confirmed_retired)) or set(retiring) & set(
        listed
    ):
        raise ValueError("period_retirement_not_confirmed")
    if mode in ("bootstrap", "history") or codes:
        if not codes and not (mode == "history" and retiring):
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
    with writer(staging) as control:
        run = safe_path(control / "runs" / run_id)
        run.mkdir(parents=True, exist_ok=True)
        manifest = run / "manifest.json"
        if manifest.exists():
            saved = read_json(manifest)
            verify_execution(saved, run_id)
            if saved["identity"] != identity:
                raise ValueError("period_manifest_changed")
        else:
            # One initial free-space check. Newly written bytes are subsequently counted from receipts.
            if shutil.disk_usage(staging).free < policy.workspace_bytes:
                raise ValueError("period_workspace_free_space_insufficient")
            saved = {
                "identity": identity,
                "identity_hash": digest(identity),
                "phase": "deleting" if mode == "bootstrap" else "download",
            }
            atomic_json(manifest, saved)
        baseline = control / "baseline.json"
        if mode != "bootstrap" and (
            not baseline.exists() or read_json(baseline).get("status") != "ready"
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
            atomic_json(baseline, {"status": "rebuilding", "run_id": run_id})
            for freq in freqs:
                remove_dataset(root, freq, cancel)
            saved["phase"] = "download"
            atomic_json(manifest, saved)
        changed = []
        prepared = []
        for freq in freqs:
            candidates_file = run / f"{freq}.candidates.json"
            if candidates_file.exists():
                candidates = read_json(candidates_file)
                if saved.get("candidate_hashes", {}).get(freq) != digest(candidates):
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
                        request_id=intent["request_id"],
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
                    if used > policy.workspace_bytes:
                        raise ValueError("period_workspace_budget_exceeded")
                    progress(
                        {
                            "stage": "source_unit_complete",
                            "freq": freq,
                            "completed": index + 1,
                            "total": len(scope),
                        }
                    )
                other_bytes = sum(
                    v for k, v in saved.get("source_bytes", {}).items() if k != freq
                )
                if used + other_bytes + policy.spill_bytes > policy.workspace_bytes:
                    raise ValueError("period_workspace_budget_exceeded")
                paths = [p["csv"] for u in units for p in u["pages"]]
                build = run / "build" / freq
                # An interrupted COPY has no complete manifest; only its private disposable candidates rebuild.
                if build.exists() and not (build / "copy.json").exists():
                    safe_path(build)
                    shutil.rmtree(build)
                candidates = assemble(
                    paths,
                    work=build,
                    root=root,
                    mode=mode,
                    freq=freq,
                    codes=codes,
                    retired_codes=retiring,
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
                other_outputs = sum(
                    v for k, v in saved.get("candidate_bytes", {}).items() if k != freq
                )
                if (
                    used
                    + other_bytes
                    + candidate_bytes
                    + other_outputs
                    + policy.spill_bytes
                    > policy.workspace_bytes
                ):
                    raise ValueError("period_workspace_budget_exceeded")
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
            with connection(run / "commit", policy) as con:
                for index, item in enumerate(candidates):
                    check_cancel(cancel)
                    cp = run / "committed" / freq / f"{item['period']}.json"
                    result = publish(item, checkpoint=cp, con=con, cancel=cancel)
                    changed.append(result)
                    progress(
                        {
                            "stage": "file_committed",
                            "freq": freq,
                            "completed": index + 1,
                            "total": len(candidates),
                        }
                    )
        _record_ranges(baseline, run, intent, changed)
        # Events/state are downstream of file commits and can be retried without data work.
        for item in changed if events is not None else []:
            check_cancel(cancel)
            eventcp = run / "events" / item["freq"] / f"{item['period']}.json"
            if not eventcp.exists():
                events(item)
                atomic_json(eventcp, {"version": item["version"]})
        saved["phase"] = "complete" if events is not None else "files_complete"
        atomic_json(manifest, saved)
        if mode == "bootstrap":
            atomic_json(
                baseline,
                {
                    **read_json(baseline),
                    "status": "ready" if events is not None else "files_ready",
                    "run_id": run_id,
                    "listed": sorted(listed),
                    "files": [
                        {
                            k: i[k]
                            for k in ("freq", "period", "target", "version", "rows")
                        }
                        for i in changed
                    ],
                },
            )
        atomic_json(run / "complete.json", {"run_id": run_id, "files": changed})
        return {
            "run_id": run_id,
            "files": changed,
            "path": str(run),
            "unit_asofs": saved.get("unit_asofs", {}),
        }
