"""Period Raw coordinator: fixed-root reset, capture, columnar build, commit and event resume."""

from __future__ import annotations

import fcntl
import os
import re
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


def _finish_files(run, saved, changed):
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


def verify_rss_resume(staging, run_id, identity):
    manifest = safe_path(staging / "stock_period/runs" / run_id / "manifest.json")
    if not manifest.is_file() or identity["intent"]["mode"] != "bootstrap":
        raise ValueError("period_runtime_rss_resume_required")
    saved = read_json(manifest)
    verify_execution(saved, run_id)
    if saved["identity"] != identity:
        raise ValueError("period_manifest_changed")


def replay_events(run, *, root, staging, events=None, cancel=lambda: False):
    """Only this bootstrap's files and actual native events determine completion."""
    root, staging = roots(root, staging)
    with writer(staging):
        run = safe_path(run)
        if run != staging / "stock_period/runs" / run.name:
            raise ValueError("period_event_run_path_invalid")
        saved = read_json(run / "manifest.json")
        verify_execution(saved, run.name)
        if (
            saved["identity"]["intent"]["mode"] != "bootstrap"
            or saved["identity"]["root"] != str(root)
            or saved["phase"] not in ("files_complete", "events_complete")
        ):
            raise ValueError("period_event_files_incomplete")
        check_devices(root, staging, saved["devices"])
        complete = completed_files(run, saved, cancel=cancel)
        done = events is not None and events(complete["files"]) is True
        if done:
            saved["phase"] = "events_complete"
            atomic_json(run / "manifest.json", saved)
        return {**complete, "path": str(run), "events_complete": done}


def run_period(
    *,
    root,
    staging,
    intent,
    listed,
    aliases,
    transport=None,
    policy=DEFAULT_POLICY,
    runtime_rss_bytes=None,
    cancel=lambda: False,
    progress=lambda _: None,
):
    """Independent first-time bootstrap; no daily or manual history dispatch."""
    if runtime_rss_bytes is not None and (
        type(runtime_rss_bytes) is not int or runtime_rss_bytes <= 0
    ):
        raise ValueError("period_runtime_rss_limit_invalid")
    root, staging = roots(root, staging)
    initial_devices = devices(root, staging)
    if initial_devices["root"] != initial_devices["staging"]:
        raise ValueError("period_atomic_device_mismatch")
    if intent.get("version") != VERSION or intent.get("mode") != "bootstrap":
        raise ValueError("period_intent_version_or_mode_invalid")
    if not listed:
        raise ValueError("period_listed_scope_empty")
    freqs, codes = intent["frequencies"], sorted(set(intent.get("codes", [])))
    if len(freqs) != 2 or set(freqs) != {"week", "month"} or set(codes) != set(listed):
        raise ValueError("period_bootstrap_scope_incomplete")
    for code in codes:
        admitted_code(code, listed, aliases)
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
        if manifest.exists():
            saved = read_json(manifest)
            verify_execution(saved, run_id)
            if saved["identity"] != identity:
                raise ValueError("period_manifest_changed")
            check_devices(root, staging, saved["devices"])
            if saved["phase"] in ("files_complete", "events_complete"):
                return {
                    **completed_files(run, saved, cancel=cancel),
                    "path": str(run),
                    "events_complete": False,
                }
        else:
            run.mkdir(parents=True, exist_ok=True)
            saved = {
                "identity": identity,
                "identity_hash": digest(identity),
                "phase": "deleting",
                "devices": initial_devices,
                "started_at": execution_time(),
            }
            atomic_json(manifest, saved)
        budget = StorageBudget(run, policy, cancel=cancel, progress=progress)
        token = _BUDGET.set(budget)
        budget.guard = lambda: check_devices(root, staging, saved["devices"])
        try:
            if saved["phase"] == "deleting":
                if root.exists():
                    sync_directory(root)
                for freq in freqs:
                    check_devices(root, staging, saved["devices"])
                    remove_dataset(root, freq, cancel)
                saved["phase"] = "download"
                atomic_json(manifest, saved)
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
                    transport = transport or HttpPage(
                        policy=policy, cancel=cancel, progress=progress
                    )
                    for index, code in enumerate(codes):
                        check_cancel(cancel)
                        _rss(policy)
                        units.append(
                            capture_unit(
                                work=run / "source",
                                request_id=intent["request_id"],
                                freq=freq,
                                listed=listed,
                                aliases=aliases,
                                code=code,
                                transport=transport,
                                policy=policy,
                                cancel=cancel,
                                progress=progress,
                            )
                        )
                        progress(
                            {
                                "stage": "source_unit_complete",
                                "freq": freq,
                                "completed": index + 1,
                                "total": len(codes),
                            }
                        )
                    build = run / "build" / freq
                    if build.exists() and not (build / "copy.json").exists():
                        safe_path(build)
                        shutil.rmtree(build)
                        budget.forget_tree(build)
                    candidates = assemble(
                        [p["csv"] for u in units for p in u["pages"]],
                        work=build,
                        root=root,
                        mode="bootstrap",
                        freq=freq,
                        codes=codes,
                        policy=policy,
                        cancel=cancel,
                        progress=progress,
                    )
                    saved.setdefault("unit_asofs", {})[freq] = {
                        u["identity"]["code"]: u["maximum_asof"] for u in units
                    }
                    saved.setdefault("source_bytes", {})[freq] = sum(
                        p["bytes"] + p["csv_version"][2]
                        for u in units
                        for p in u["pages"]
                    )
                    saved.setdefault("candidate_bytes", {})[freq] = sum(
                        i["version"][2] for i in candidates
                    )
                    asofs = [u["maximum_asof"] for u in units]
                    saved.setdefault("source_asof", {})[freq] = (
                        min(asofs) if asofs and all(asofs) else None
                    )
                    saved.setdefault("candidate_hashes", {})[freq] = digest(candidates)
                    atomic_json(manifest, saved)
                    atomic_json(candidates_file, candidates)
                prepared.append((freq, candidates))
            changed = []
            for freq, candidates in prepared:
                for index, item in enumerate(candidates):
                    check_cancel(cancel)
                    check_devices(root, staging, saved["devices"])
                    budget.reserve(device=target_parent(item["target"]))
                    changed.append(
                        publish(
                            item,
                            checkpoint=run
                            / "committed"
                            / freq
                            / (item["period"] + ".json"),
                            cancel=cancel,
                        )
                    )
                    progress(
                        {
                            "stage": "file_committed",
                            "freq": freq,
                            "completed": index + 1,
                            "total": len(candidates),
                        }
                    )
            _finish_files(run, saved, changed)
            return {
                **completed_files(run, saved, cancel=cancel),
                "path": str(run),
                "events_complete": False,
            }
        finally:
            _BUDGET.reset(token)


def _bootstrap_event_evidence(instance, files, *, materializations=True, checks=True):
    """Two collection queries for exact current units, independent of unit count."""
    import dagster as dg
    import sqlalchemy as sa
    from dagster._core.event_api import EventLogRecord
    from dagster._core.events.log import EventLogEntry
    from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
    from dagster._core.storage.event_log.sql_event_log import SqlEventLogStorage
    from dagster._serdes import deserialize_value

    from orchestrator.defs.asset_guards.stock_period_check_evidence import (
        decode_completed_check_row,
        latest_completed_checks_query,
    )
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )

    if not files:
        return {}
    storage = instance.event_log_storage
    if not isinstance(storage, SqlEventLogStorage):
        raise TypeError("period_event_storage_unsupported")
    by_asset = {}
    result = {}
    for item in files:
        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
        by_asset.setdefault(asset, set()).add(item["period"])
        result[(asset.to_user_string(), item["period"])] = {
            "materialization": None,
            "checks": {},
        }
    predicates = [
        sa.and_(
            Events.c.asset_key == asset.to_string(),
            Events.c.partition.in_(sorted(periods)),
        )
        for asset, periods in by_asset.items()
    ]
    latest_mats = (
        sa.select(sa.func.max(Events.c.id))
        .where(
            Events.c.dagster_event_type == "ASSET_MATERIALIZATION", sa.or_(*predicates)
        )
        .group_by(Events.c.asset_key, Events.c.partition)
    )
    selected_checks = latest_completed_checks_query(
        asset_check_names={
            asset: raw_check_names(
                "week" if asset.to_user_string().endswith("_week") else "month"
            )
            for asset in by_asset
        },
        partition_keys=sorted(
            {period for periods in by_asset.values() for period in periods}
        ),
    )
    exact_check_pairs = [
        sa.and_(
            selected_checks.c.asset_key == asset.to_string(),
            selected_checks.c.partition.in_(sorted(periods)),
        )
        for asset, periods in by_asset.items()
    ]
    with storage.index_connection() as connection:
        mat_rows = (
            connection.execute(
                sa.select(Events.c.id, Events.c.event).where(
                    Events.c.id.in_(latest_mats)
                )
            )
            .mappings()
            .all()
            if materializations
            else []
        )
        check_rows = (
            connection.execute(
                sa.select(selected_checks).where(sa.or_(*exact_check_pairs))
            )
            .mappings()
            .all()
            if checks
            else []
        )
    for row in mat_rows:
        record = EventLogRecord(
            row["id"], deserialize_value(row["event"], EventLogEntry)
        )
        materialization = record.asset_materialization
        key = (materialization.asset_key.to_user_string(), materialization.partition)
        if key not in result:
            raise ValueError("period_delivery_materialization_invalid")
        result[key]["materialization"] = record
    for row in check_rows:
        asset = dg.AssetKey.from_db_string(row["asset_key"])
        key = (asset.to_user_string(), row["partition"])
        if key not in result:
            raise ValueError("period_check_evidence_scope_invalid")
        result[key]["checks"][row["check_name"]] = decode_completed_check_row(
            row,
            asset_key=asset,
            check_name=row["check_name"],
            partition_key=row["partition"],
        )
    return result


def report_bootstrap_events(instance, context, files, *, cancel=lambda: False):
    """Report this bootstrap only; bounded collections, exact original checks, no daily notice."""
    import dagster as dg
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )
    from orchestrator.defs.io.stock_period_raw import audit_file
    from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
    from orchestrator.defs.run_contracts.stock_period import FIELDS

    def matches(record, item):
        if record is None:
            return False
        mat = record.asset_materialization
        return (
            mat.partition == item["period"]
            and mat.asset_key.to_user_string()
            == f"raw_tushare_stk_period_bar_adj_{item['freq']}"
            and getattr(mat.metadata.get("dagster/uri"), "value", None)
            == item["target"]
            and getattr(mat.metadata.get("dagster/row_count"), "value", None)
            == item["rows"]
            and getattr(
                mat.metadata.get("goldenshare/period_file_version"), "value", None
            )
            == item["version"]
        )

    def valid_check(selected, record, item):
        check, _, bound = selected
        evaluation = check.evaluation
        return (
            matches(record, item)
            and check.status.value == "SUCCEEDED"
            and evaluation is not None
            and evaluation.passed
            and evaluation.blocking
            and bound is not None
            and bound.storage_id == record.storage_id
        )

    for item in files:
        check_cancel(cancel)
        evidence = audit_file(
            Path(item["target"]).parents[4], item["freq"], item["period"]
        )
        if any(evidence[k] != item[k] for k in ("rows", "version", "sha256")):
            raise ValueError("period_event_receipt_mismatch")
    before = _bootstrap_event_evidence(instance, files)
    for item in files:
        key = (f"raw_tushare_stk_period_bar_adj_{item['freq']}", item["period"])
        evidence = before[key]
        record = evidence["materialization"]
        if record is not None and not matches(record, item):
            raise ValueError("period_event_materialization_invalid")
        if any(not valid_check(c, record, item) for c in evidence["checks"].values()):
            raise ValueError("period_event_checks_invalid")
    for freq in ("week", "month"):
        periods = sorted({i["period"] for i in files if i["freq"] == freq})
        if periods:
            instance.add_dynamic_partitions(
                "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months",
                periods,
            )
    for item in files:
        check_cancel(cancel)
        key = (f"raw_tushare_stk_period_bar_adj_{item['freq']}", item["period"])
        if before[key]["materialization"] is None:
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=key[0],
                    partition=key[1],
                    metadata=build_materialization_metadata(
                        uri=item["target"],
                        row_count=item["rows"],
                        observed_columns=FIELDS,
                        extra_metadata={
                            "goldenshare/period_file_version": dg.MetadataValue.json(
                                item["version"]
                            )
                        },
                    ),
                )
            )
    current = _bootstrap_event_evidence(instance, files, checks=False)
    op_context = getattr(context, "op_execution_context", context)
    for item in files:
        key = (f"raw_tushare_stk_period_bar_adj_{item['freq']}", item["period"])
        record = current[key]["materialization"]
        if not matches(record, item):
            raise ValueError("period_event_materialization_invalid")
        for name in raw_check_names(item["freq"]):
            check_cancel(cancel)
            if name in before[key]["checks"]:
                continue
            instance.report_dagster_event(
                DagsterEvent(
                    event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                    job_name=op_context.job_name,
                    step_key=op_context.get_step_execution_context().step.key,
                    event_specific_data=AssetCheckEvaluation(
                        asset_key=record.asset_materialization.asset_key,
                        check_name=name,
                        partition=item["period"],
                        passed=True,
                        blocking=True,
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=record.storage_id,
                            run_id=record.event_log_entry.run_id,
                            timestamp=record.timestamp,
                        ),
                    ),
                ),
                run_id=op_context.run_id,
            )
    after = _bootstrap_event_evidence(instance, files, materializations=False)
    for item in files:
        check_cancel(cancel)
        key = (f"raw_tushare_stk_period_bar_adj_{item['freq']}", item["period"])
        if file_version(item["target"]) != item["version"] or set(
            after[key]["checks"]
        ) != set(raw_check_names(item["freq"])):
            raise ValueError("period_event_checks_incomplete")
        if any(
            not valid_check(c, current[key]["materialization"], item)
            for c in after[key]["checks"].values()
        ):
            raise ValueError("period_event_checks_invalid")
    return True
