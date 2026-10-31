"""Source-only columnar assembly and per-file atomic publication for period Raw."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import stat
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.run_contracts.stock_period import (
    DEFAULT_POLICY,
    FIELDS,
    VERSION,
    digest,
    frequency,
    next_period,
    period_date,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
)

SPECS = tuple(
    (n, t) for n, t, _ in weekly_column_specs(StockWeeklySource.PRIMARY_ADJUSTED)
)
COLUMNS = ",".join(f'"{n}"' for n in FIELDS)
PERIOD_SQL = "CASE WHEN freq='week' THEN strftime(date_trunc('week',strptime(trade_date,'%Y%m%d'))+INTERVAL 4 DAY,'%Y-%m-%d') ELSE substr(trade_date,1,4)||'-'||substr(trade_date,5,2) END"


class PeriodCancelled(RuntimeError):
    pass


def check_cancel(cancel):
    if cancel():
        raise PeriodCancelled("period_cancelled")


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("period_path_invalid")
    for component in (*reversed(path.parents), path):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("period_symlink_forbidden")
    return path


_BUDGET = ContextVar("period_storage_budget", default=None)
_PROCESS_MEMORY = ContextVar("period_process_memory", default=None)


def sync_directory(path):
    descriptor = os.open(safe_path(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_directory(path):
    path = safe_path(path)
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        sync_directory(directory.parent)
    return path


def atomic_json(path, value):
    path = safe_path(path)
    durable_directory(path.parent)
    tmp = safe_path(path.with_suffix(path.suffix + ".tmp"))
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    budget = _BUDGET.get()
    if budget is not None:
        budget.reserve(len(payload))
    try:
        with tmp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        sync_directory(path.parent)
    finally:
        if budget is not None:
            budget.record(path)
            budget.record(tmp)


@lru_cache(maxsize=1)
def _mach_resident_reader():
    # ABI from the installed macOS SDK mach/task_info.h: MACH_TASK_BASIC_INFO=20.
    class TaskInfo(ctypes.Structure):
        _fields_ = [
            ("virtual", ctypes.c_uint64),
            ("resident", ctypes.c_uint64),
            ("peak", ctypes.c_uint64),
            ("times", ctypes.c_int32 * 4),
            ("policy", ctypes.c_int32),
            ("suspend", ctypes.c_int32),
        ]

    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    return library, TaskInfo


def current_rss_bytes():
    if sys.platform == "darwin":
        library, info_type = _mach_resident_reader()
        task = ctypes.c_uint.in_dll(library, "mach_task_self_").value
        info = info_type()
        count = ctypes.c_uint(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint))
        if library.task_info(task, 20, ctypes.byref(info), ctypes.byref(count)) != 0:
            raise OSError("period_current_rss_unavailable")
        return info.resident
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf(
        "SC_PAGE_SIZE"
    )


class StorageBudget:
    """Run-local byte accounting. One recovery inventory; writes update known paths."""

    def __init__(self, run, policy, *, cancel=lambda: False, progress=lambda _: None):
        self.run, self.policy = Path(run), policy
        self.sizes = {}
        self.cancel, self.progress = cancel, progress
        self.used = 0
        self.guard = lambda: None
        self.inventory(self.run)

    def record(self, path):
        path = safe_path(path)
        size = path.stat().st_size if path.is_file() else 0
        self.used += size - self.sizes.get(str(path), 0)
        self.sizes[str(path)] = size
        if self.used > self.policy.workspace_bytes:
            raise ValueError("period_workspace_budget_exceeded")

    def inventory(self, root):
        import time

        emitted = time.monotonic()
        for directory, dirs, files in os.walk(
            root, onerror=lambda error: (_ for _ in ()).throw(error)
        ):
            check_cancel(self.cancel)
            for name in dirs:
                safe_path(Path(directory) / name)
            for name in files:
                path = Path(directory) / name
                self.record(path)
                if (
                    path.is_relative_to(self.run / "committed")
                    and path.suffix == ".json"
                ):
                    self.record(read_json(path)["target"])
            if time.monotonic() - emitted >= self.policy.progress_seconds:
                self.progress(
                    {
                        "stage": "storage_inventory",
                        "files": len(self.sizes),
                        "bytes": self.used,
                    }
                )
                emitted = time.monotonic()

    def reserve(self, addition=0, *, spill=False, device=None):
        check_cancel(self.cancel)
        self.guard()
        reservation = addition + (self.policy.spill_bytes if spill else 0)
        if self.used + reservation > self.policy.workspace_bytes:
            raise ValueError("period_workspace_budget_exceeded")
        if shutil.disk_usage(device or self.run).free < reservation:
            raise ValueError("period_workspace_free_space_insufficient")

    def forget_tree(self, root):
        for path in list(self.sizes):
            if Path(path).is_relative_to(root):
                self.used -= self.sizes.pop(path)

    def moved(self, source, target):
        self.used -= self.sizes.pop(str(source), 0)
        self.record(target)


def storage_reserve(addition=0, *, spill=False):
    budget = _BUDGET.get()
    if budget is not None:
        budget.reserve(addition, spill=spill)


def storage_record(path):
    budget = _BUDGET.get()
    if budget is not None:
        budget.record(path)


def read_json(path):
    return json.loads(safe_path(path).read_text())


def file_version(path):
    st = safe_path(path).stat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("period_regular_file_required")
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def file_digest(path):
    h = hashlib.sha256()
    with safe_path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def _dataset_root_path(root, freq):
    """Compose the fixed dataset path without inspecting the filesystem."""
    root = Path(root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("period_path_invalid")
    return root / "raw" / "tushare" / f"stk_period_bar_adj_{frequency(freq)}"


def _target_path(root, freq, period):
    """The same canonical target identity for metadata and guarded IO."""
    period_date(period, freq)
    base = _dataset_root_path(root, freq)
    return (
        base
        / (f"week_end={period}" if freq == "week" else f"month={period}")
        / ("part-000.parquet" if freq == "week" else "data.parquet")
    )


def dataset_root(root, freq):
    return safe_path(_dataset_root_path(root, freq))


def target_path(root, freq, period):
    return safe_path(_target_path(root, freq, period))


def connection(work, policy=DEFAULT_POLICY):
    return connect_configured_duckdb(
        DuckDBConnectionSettings(
            temp_directory=Path(work) / "spill",
            max_temp_directory_size=f"{policy.spill_bytes}B",
            memory_limit=policy.duckdb_memory,
            threads=policy.duckdb_threads,
        )
    )


@contextmanager
def process_memory_budget(policy, rss_limit_bytes=None, *, progress=lambda _: None):
    """Execution-only RSS override; frozen source/execution policies stay intact."""
    if rss_limit_bytes is not None and (
        type(rss_limit_bytes) is not int or rss_limit_bytes <= 0
    ):
        raise ValueError("period_runtime_rss_limit_invalid")
    observed = (
        {
            "frozen_rss_limit_bytes": policy.rss_bytes,
            "rss_limit_bytes": rss_limit_bytes,
            "last_observed_rss_bytes": 0,
            "observed_peak_rss_bytes": 0,
        }
        if rss_limit_bytes is not None
        else None
    )
    token = _PROCESS_MEMORY.set(observed)
    try:
        if observed is not None:
            check_memory(policy)
            progress({"stage": "process_memory", "status": "started", **observed})
        yield
    finally:
        error = sys.exc_info()[1]
        _PROCESS_MEMORY.reset(token)
        if observed is not None:
            try:
                progress(
                    {
                        "stage": "process_memory",
                        "status": "failed" if error else "finished",
                        **observed,
                    }
                )
            except Exception:
                # Reporting must not replace an active execution error.
                if error is None:
                    raise


def check_memory(policy):
    resident = current_rss_bytes()
    observed = _PROCESS_MEMORY.get()
    limit = policy.rss_bytes
    if observed is not None:
        limit = observed["rss_limit_bytes"]
        observed["last_observed_rss_bytes"] = resident
        observed["observed_peak_rss_bytes"] = max(
            observed["observed_peak_rss_bytes"], resident
        )
    if resident > limit:
        raise ValueError("period_process_memory_exceeded")


def execute(
    con,
    sql,
    parameters=None,
    *,
    cancel=lambda: False,
    progress=lambda _: None,
    stage="sql",
    policy=DEFAULT_POLICY,
):
    """Serialize SQL on one connection; keep the main thread responsive to TERM."""
    import time

    check_cancel(cancel)
    check_memory(policy)
    parameters = list(parameters or [])
    if sql.startswith("COPY ") and " TO ? " in sql:
        output = str(safe_path(parameters.pop()))
        sql = sql.replace(" TO ? ", " TO '" + output.replace("'", "''") + "' ", 1)
    errors, results = [], []
    completed = threading.Event()

    def query():
        try:
            results.append(con.execute(sql, parameters))
        except BaseException as error:  # noqa: BLE001 -- Re-raised on the coordinating thread.
            errors.append(error)
        finally:
            completed.set()

    # This replaces the previous monitor thread; SQL calls never overlap.
    worker = threading.Thread(target=query, daemon=True)
    worker.start()
    emitted = time.monotonic()
    try:
        while not completed.wait(0.05):
            check_cancel(cancel)
            check_memory(policy)
            if time.monotonic() - emitted >= policy.progress_seconds:
                progress(
                    {
                        "stage": stage,
                        "status": "working",
                        "business_completed_unchanged": True,
                        **(_PROCESS_MEMORY.get() or {}),
                    }
                )
                emitted = time.monotonic()
        check_cancel(cancel)
        check_memory(policy)
        if errors:
            raise errors[0]
        progress({"stage": stage, **(_PROCESS_MEMORY.get() or {})})
        return results[0]
    finally:
        # Repeat interrupt until the query has actually exited, covering the
        # start/interrupt race. Never release the writer while it can still COPY.
        while worker.is_alive():
            if not completed.is_set():
                con.interrupt()
            worker.join(0.05)


def validate_file(
    con, path, freq, period, *, cancel=lambda: False, policy=DEFAULT_POLICY
):
    before = file_version(path)
    schema = [
        tuple(r[:2])
        for r in execute(
            con,
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
            cancel=cancel,
            policy=policy,
            stage="file_schema",
        ).fetchall()
    ]
    if schema != list(SPECS):
        raise ValueError("period_file_schema_invalid")
    rows, unique, invalid = execute(
        con,
        f"""SELECT count(*),count(DISTINCT(ts_code,trade_date,freq)),
        count(*) FILTER(WHERE ts_code IS NULL OR NOT regexp_full_match(ts_code,'[0-9]{{6}}\\.(SH|SZ|BJ)')
        OR freq IS DISTINCT FROM ? OR trade_date IS NULL
        OR NOT regexp_full_match(trade_date,'[0-9]{{8}}') OR try_strptime(trade_date,'%Y%m%d') IS NULL
        OR (end_date IS NOT NULL AND (NOT regexp_full_match(end_date,'[0-9]{{8}}') OR try_strptime(end_date,'%Y%m%d') IS NULL))
        OR ({PERIOD_SQL}) IS DISTINCT FROM ?)
        FROM read_parquet(?,hive_partitioning=false)""",
        [freq, period, str(path)],
        cancel=cancel,
        policy=policy,
    ).fetchone()
    if rows != unique or invalid or before != file_version(path):
        raise ValueError("period_file_key_or_partition_invalid")
    return {"rows": rows, "version": before, "sha256": file_digest(path)}


def range_index_valid(evidence):
    """Metadata integrity only; current files are checked for the selected scope."""
    return (
        isinstance(evidence, dict)
        and evidence.get("range_index_version") == VERSION
        and isinstance(evidence.get("files"), list)
        and isinstance(evidence.get("stock_ranges"), dict)
        and evidence.get("range_index_hash")
        == digest({k: evidence[k] for k in ("files", "stock_ranges")})
    )


def _old_range_paths(root, freq, codes, evidence):
    """Resolve approved old periods without opening or enumerating lake files."""
    if not range_index_valid(evidence):
        raise ValueError("period_history_range_unverified")
    registered, paths = {}, set()
    for item in evidence["files"]:
        if not isinstance(item, dict) or item.get("freq") not in ("week", "month"):
            raise ValueError("period_range_registration_invalid")
        period_date(item.get("period"), item["freq"])
        key = (item["freq"], item["period"])
        version = item.get("version")
        if (
            key in registered or not isinstance(item.get("target"), str)
            or item["target"] in paths or not isinstance(version, list)
            or len(version) != 5
            or any(type(value) is not int or value < 0 for value in version)
            or type(item.get("rows")) is not int or item["rows"] < 0
        ):
            raise ValueError("period_range_registration_invalid")
        registered[key] = item
        paths.add(item["target"])
    ranges = evidence["stock_ranges"].get(freq)
    if not isinstance(ranges, dict) or not isinstance(evidence.get("listed"), list):
        raise TypeError("period_history_range_unverified")
    selected = set()
    for code in sorted(codes):
        if code not in ranges:
            if code in evidence["listed"]:
                raise ValueError("period_history_range_unverified")
            continue  # A new code has no rows in the complete approved index.
        intervals = ranges[code]
        if not isinstance(intervals, list) or not intervals:
            raise ValueError("period_history_range_unverified")
        for interval in intervals:
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError("period_history_range_unverified")
            first, last = interval
            period_date(first, freq)
            period_date(last, freq)
            if first > last:
                raise ValueError("period_history_range_unverified")
            period = first
            while period <= last:
                item = registered.get((freq, period))
                if item is None or item["target"] != str(target_path(root, freq, period)):
                    raise ValueError("period_range_registration_invalid")
                selected.add(period)
                if period == last:
                    break
                period = next_period(period, freq)
    return [(registered[(freq, period)]["target"], period) for period in sorted(selected)]


def _source_ranges(con, freq, *, cancel, progress, policy):
    coordinate = (
        "date_diff('week',DATE '1970-01-02',period::DATE)"
        if freq == "week"
        else "CAST(substr(period,1,4) AS INTEGER)*12+CAST(substr(period,6,2) AS INTEGER)"
    )
    cursor = execute(
        con,
        f"WITH p AS (SELECT DISTINCT ts_code,period FROM source), n AS "
        f"(SELECT ts_code,period,{coordinate}-row_number() OVER(PARTITION BY ts_code ORDER BY period) g FROM p) "
        "SELECT ts_code,min(period),max(period) FROM n GROUP BY ts_code,g ORDER BY ts_code,min(period)",
        cancel=cancel,
        progress=progress,
        policy=policy,
        stage="source_range_facts",
    )
    result = {}
    while rows := cursor.fetchmany(policy.page_limit):
        check_cancel(cancel)
        for code, first, last in rows:
            result.setdefault(code, []).append([first, last])
    return result


def merge_ranges(prior, incoming, freq):
    result = []
    for first, last in sorted(prior + incoming):
        if result and first <= next_period(result[-1][1], freq):
            result[-1][1] = max(result[-1][1], last)
        else:
            result.append([first, last])
    return result


def assemble(
    sources,
    *,
    work,
    root,
    mode,
    freq,
    codes=(),
    retired_codes=(),
    periods=(),
    history_sources=(),
    range_evidence=None,
    policy=DEFAULT_POLICY,
    cancel=lambda: False,
    progress=lambda _: None,
    validate_targets=None,
):
    """Import all successful pages once. Each affected partition is assembled once."""
    if mode not in ("bootstrap", "upsert", "history"):
        raise ValueError("period_write_mode_invalid")
    frequency(freq)
    work = safe_path(work)
    work.mkdir(parents=True, exist_ok=True)
    if mode == "history" and not codes and not retired_codes:
        raise ValueError("period_history_scope_empty")
    identity = {
        "sources": [[str(p), file_version(p)] for p in sources],
        "root": str(root),
        "mode": mode,
        "freq": freq,
        "codes": sorted(codes),
        "retired_codes": sorted(retired_codes),
        "periods": sorted(periods),
        "history_sources": sorted(str(p) for p in history_sources),
    }
    copy_receipt = work / "copy.json"
    if copy_receipt.exists():
        copied = read_json(copy_receipt)
        if copied["identity"] != identity:
            raise ValueError("period_assembly_input_changed")
        if validate_targets is not None:
            validate_targets(
                [
                    {
                        "freq": freq,
                        "period": period,
                        "target": str(target_path(root, freq, period)),
                        "version": file_version(target_path(root, freq, period))
                        if target_path(root, freq, period).exists()
                        else None,
                        "target_preimage": copied["target_preimages"][period],
                    }
                    for period in copied["periods"]
                ]
            )
        with connection(work, policy) as con:
            return _candidate_receipts(
                con, copied["periods"], work, root, freq, cancel, progress, policy
            )
    schema = dict(SPECS)
    with connection(work, policy) as con:
        if sources:
            execute(
                con,
                "CREATE TEMP TABLE incoming AS SELECT * FROM read_csv(?,header=true,columns=?,nullstr='',filename=true)",
                [[str(safe_path(p)) for p in sources], schema],
                cancel=cancel,
                progress=progress,
                stage="import_source",
                policy=policy,
            )
        else:
            execute(
                con,
                "CREATE TEMP TABLE incoming ("
                + ",".join((f'"{n}" {t}' for n, t in SPECS))
                + ",filename VARCHAR)",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            )
        if execute(
            con,
            "SELECT count(*) FROM incoming WHERE freq<>?",
            [freq],
            cancel=cancel,
            policy=policy,
            stage="source_integrity",
            progress=progress,
        ).fetchone()[0]:
            raise ValueError("period_source_frequency_mixed")
        if (
            not execute(
                con,
                "SELECT count(*) FROM incoming",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchone()[0]
            and not retired_codes
        ):
            raise ValueError("period_source_empty")
        history_paths = [
            str(p) for p in (sources if mode == "history" else history_sources)
        ]
        if history_paths and not set(history_paths).issubset(set(map(str, sources))):
            raise ValueError("period_history_inputs_missing")
        actual = {
            r[0]
            for r in execute(
                con,
                "SELECT DISTINCT ts_code FROM incoming WHERE list_contains(?,filename)",
                [history_paths],
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchall()
        }
        if actual != set(codes) and mode != "bootstrap":
            raise ValueError("period_history_codes_mismatch")
        # Repeated keys across current/history snapshots may coalesce only as identical full rows.
        conflict = execute(
            con,
            f"SELECT ts_code,trade_date,freq FROM incoming GROUP BY 1,2,3 HAVING count(DISTINCT ROW({COLUMNS}))>1 LIMIT 1",
            cancel=cancel,
            policy=policy,
            stage="source_integrity",
            progress=progress,
        ).fetchone()
        if conflict:
            atomic_json(
                work / "conflict.json",
                {
                    "reason_code": "period_source_conflicting_key",
                    "key": list(conflict),
                    "sources": identity["sources"],
                },
            )
            raise ValueError("period_source_conflicting_key")
        if (
            not (mode == "upsert" and codes)
            and execute(
                con,
                "SELECT count(*)-count(DISTINCT(ts_code,trade_date,freq)) FROM incoming",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchone()[0]
        ):
            raise ValueError("period_source_duplicate_key")
        if mode == "upsert" and codes:
            absent = execute(
                con,
                "SELECT ts_code,trade_date,freq FROM incoming p WHERE list_contains(?,p.ts_code) AND NOT list_contains(?,p.filename) AND NOT EXISTS (SELECT 1 FROM incoming h WHERE list_contains(?,h.filename) AND h.ts_code=p.ts_code AND h.trade_date=p.trade_date AND h.freq=p.freq) LIMIT 1",
                [list(codes), history_paths, history_paths],
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchone()
            if absent:
                atomic_json(
                    work / "conflict.json",
                    {
                        "reason_code": "period_history_coverage_conflict",
                        "key": list(absent),
                    },
                )
                raise ValueError("period_history_coverage_conflict")
        execute(
            con,
            f"CREATE TEMP TABLE source AS SELECT DISTINCT {COLUMNS},{PERIOD_SQL} AS period FROM incoming",
            cancel=cancel,
            policy=policy,
            stage="source_integrity",
            progress=progress,
        )
        selected = {
            r[0]
            for r in execute(
                con,
                "SELECT DISTINCT period FROM source",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchall()
        }
        if (
            mode == "upsert"
            and execute(
                con,
                f"SELECT count(*) FROM incoming WHERE NOT list_contains(?,filename) AND NOT list_contains(?,{PERIOD_SQL})",
                [history_paths, list(periods)],
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            ).fetchone()[0]
        ):
            raise ValueError("period_source_scope_mismatch")
        oldpaths = []
        index_valid = mode == "bootstrap" or range_index_valid(range_evidence)
        if mode == "history" or (mode == "upsert" and (codes or retired_codes)):
            affected = _old_range_paths(
                root, freq, set(codes) | set(retired_codes), range_evidence
            )
            progress({"stage": "reuse_old_ranges", "files": len(affected)})
            selected.update(r[1] for r in affected)
            oldpaths.extend(r[0] for r in affected)
        if mode != "bootstrap":
            oldpaths.extend(
                str(target_path(root, freq, p))
                for p in selected
                if target_path(root, freq, p).exists()
            )
            oldpaths = sorted(set(oldpaths))
        preimages = {
            p: file_version(target_path(root, freq, p))
            if target_path(root, freq, p).exists()
            else None
            for p in selected
        }
        if mode == "bootstrap" and any(v is not None for v in preimages.values()):
            raise ValueError("period_bootstrap_root_not_empty")
        if validate_targets is not None:
            validate_targets(
                [
                    {
                        "freq": freq,
                        "period": period,
                        "target": str(target_path(root, freq, period)),
                        "version": version,
                        "target_preimage": version,
                    }
                    for period, version in sorted(preimages.items())
                ]
            )
        if oldpaths:
            execute(
                con,
                f"CREATE TEMP TABLE old AS SELECT {COLUMNS},{PERIOD_SQL} AS period FROM read_parquet(?,hive_partitioning=false)",
                [oldpaths],
                cancel=cancel,
                progress=progress,
                stage="read_affected_once",
                policy=policy,
            )
        else:
            execute(
                con,
                "CREATE TEMP TABLE old AS SELECT * FROM source WHERE false",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            )
        if mode == "history":
            execute(
                con,
                "CREATE TEMP TABLE combined AS SELECT * FROM old WHERE NOT list_contains(?,ts_code) UNION ALL SELECT * FROM source",
                [sorted(set(codes) | set(retired_codes))],
                cancel=cancel,
                progress=progress,
                stage="replace_stock_history",
                policy=policy,
            )
        elif mode == "upsert":
            execute(
                con,
                "CREATE TEMP TABLE combined AS SELECT * FROM old o WHERE NOT list_contains(?,o.ts_code) AND NOT EXISTS (SELECT 1 FROM source s WHERE s.ts_code=o.ts_code AND s.trade_date=o.trade_date AND s.freq=o.freq) UNION ALL SELECT * FROM source",
                [sorted(set(codes) | set(retired_codes))],
                cancel=cancel,
                progress=progress,
                stage="upsert_source_keys",
                policy=policy,
            )
        else:
            for period in selected:
                if target_path(root, freq, period).exists():
                    raise ValueError("period_bootstrap_root_not_empty")
            execute(
                con,
                "CREATE TEMP VIEW combined AS SELECT * FROM source",
                cancel=cancel,
                policy=policy,
                stage="source_integrity",
                progress=progress,
            )
        expected_rows = dict(
            execute(
                con,
                "SELECT period,count(*) FROM combined GROUP BY period",
                cancel=cancel,
                progress=progress,
                stage="combined_row_counts",
                policy=policy,
            ).fetchall()
        )
        for period, before in preimages.items():
            target = target_path(root, freq, period)
            if (file_version(target) if target.exists() else None) != before:
                raise ValueError("period_target_preimage_changed")
        # 512 bytes/validated fixed-width row plus 16KiB/file covers physical
        # columns and sample-derived Parquet overhead; spill is a reservation.
        storage_reserve(
            sum(expected_rows.values()) * 512 + len(selected) * 16384, spill=True
        )
        outputs = work / "outputs"
        safe_path(outputs)
        outputs.mkdir(exist_ok=True)
        execute(
            con,
            f"COPY (SELECT {COLUMNS},period FROM combined) TO ? (FORMAT PARQUET,PARTITION_BY(period))",
            [str(outputs)],
            cancel=cancel,
            progress=progress,
            stage="partition_copy",
            policy=policy,
        )
        for period in selected:
            out = outputs / f"period={period}"
            if not out.exists():
                # Only a verified nonempty history download may legitimately remove all old rows here.
                out.mkdir(parents=True)
                execute(
                    con,
                    f"COPY (SELECT {COLUMNS} FROM source WHERE false) TO ? (FORMAT PARQUET)",
                    [str(out / "data_0.parquet")],
                    cancel=cancel,
                    policy=policy,
                )
        atomic_json(
            copy_receipt,
            {
                "identity": identity,
                "periods": sorted(selected),
                "target_preimages": preimages,
                "stock_ranges": _source_ranges(
                    con, freq, cancel=cancel, progress=progress, policy=policy
                ),
                "range_index_valid": index_valid,
                "expected_rows": {p: expected_rows.get(p, 0) for p in selected},
            },
        )
        return _candidate_receipts(
            con, sorted(selected), work, root, freq, cancel, progress, policy
        )


def _validate_candidates(con, pending, freq, cancel, progress, policy, *, fragments=()):
    paths = [str(path) for _, path in pending]
    schema_paths = sorted(set(paths) | set(fragments))
    versions = {path: file_version(path) for path in schema_paths}
    schemas = execute(
        con,
        "SELECT file_name,list(name ORDER BY column_id),list(duckdb_type ORDER BY column_id) "
        "FROM parquet_schema(?) WHERE column_id>0 GROUP BY file_name",
        [schema_paths],
        cancel=cancel,
        progress=progress,
        stage="candidate_schemas",
        policy=policy,
    ).fetchall()
    if len(schemas) != len(schema_paths) or any(
        list(zip(names, types, strict=True)) != list(SPECS)
        for _, names, types in schemas
    ):
        raise ValueError("period_file_schema_invalid")
    rows = execute(
        con,
        f"""SELECT filename,count(*),count(DISTINCT(ts_code,trade_date,freq)),
        count(*) FILTER(WHERE ts_code IS NULL OR NOT regexp_full_match(ts_code,'[0-9]{{6}}\\.(SH|SZ|BJ)')
        OR freq IS DISTINCT FROM ? OR trade_date IS NULL
        OR NOT regexp_full_match(trade_date,'[0-9]{{8}}') OR try_strptime(trade_date,'%Y%m%d') IS NULL
        OR (end_date IS NOT NULL AND (NOT regexp_full_match(end_date,'[0-9]{{8}}') OR try_strptime(end_date,'%Y%m%d') IS NULL))),
        min({PERIOD_SQL}),max({PERIOD_SQL}),max(try_strptime(end_date,'%Y%m%d')::DATE)
        FROM read_parquet(?,hive_partitioning=false,filename=true) GROUP BY filename""",
        [freq, paths],
        cancel=cancel,
        progress=progress,
        stage="candidate_facts",
        policy=policy,
    ).fetchall()
    facts = {
        path: (count, unique, invalid, first, last, source_date)
        for path, count, unique, invalid, first, last, source_date in rows
    }
    if any(file_version(path) != version for path, version in versions.items()):
        raise ValueError("period_validated_candidate_changed")
    result = {}
    for period, path in pending:
        key = str(path)
        count, unique, invalid, first, last, source_date = facts.get(
            key, (0, 0, 0, None, None, None)
        )
        if (
            count != unique
            or invalid
            or (count and (first != period or last != period))
        ):
            raise ValueError("period_file_key_or_partition_invalid")
        result[key] = {
            "rows": count,
            "version": versions[key],
            "sha256": file_digest(path),
            "source_asof": source_date.isoformat() if source_date is not None else None,
        }
    return result


def _fragment_versions(work, period):
    directory = safe_path(work / "outputs" / f"period={period}")
    files = sorted(directory.glob("*.parquet"))
    if not files:
        raise ValueError("period_candidate_file_count_invalid")
    return {str(path): file_version(path) for path in files}


def _save_fragment_proof(path, proof):
    atomic_json(path, {**proof, "proof_hash": digest(proof)})


def _merged_candidate(
    con, work, period, fragments, expected_rows, cancel, progress, policy
):
    """Normalize only this partition; retain COPY outputs and resumable proof."""
    from uuid import uuid4

    out = safe_path(work / "merged" / f"{period}.parquet")
    cp = work / "validated" / f"{period}.json"
    if cp.exists():
        proof = read_json(cp)
        seal = proof.pop("proof_hash", None)
        if (
            seal != digest(proof)
            or proof.get("phase") not in ("merging", "merged", "validated")
            or proof.get("fragments") != fragments
            or proof.get("candidate") != str(out)
            or (proof["phase"] != "validated" and "item" in proof)
            or (proof["phase"] == "merging" and "version" in proof)
        ):
            raise ValueError("period_candidate_fragments_changed")
    else:
        if out.exists():
            raise ValueError("period_unowned_merged_candidate")
        proof = {"phase": "merging", "fragments": fragments, "candidate": str(out)}
        _save_fragment_proof(cp, proof)
    if proof["phase"] == "merging":
        if out.exists():
            # Exceptional rename/record gap only. Prove full multiset equality,
            # including NULL/Decimal, before claiming an unrecorded output.
            before = file_version(out)
            mismatch = execute(
                con,
                "WITH a AS (SELECT * FROM read_parquet(?,hive_partitioning=false)),"
                "b AS (SELECT * FROM read_parquet(?,hive_partitioning=false)) "
                "SELECT 1 FROM ((SELECT * FROM a EXCEPT ALL SELECT * FROM b) "
                "UNION ALL (SELECT * FROM b EXCEPT ALL SELECT * FROM a)) LIMIT 1",
                [[str(out)], list(fragments)],
                cancel=cancel,
                progress=progress,
                policy=policy,
                stage="candidate_merge_recovery",
            ).fetchone()
            if mismatch or before != file_version(out):
                raise ValueError("period_unowned_merged_candidate")
            with out.open("rb") as handle:
                os.fsync(handle.fileno())
        else:
            check_cancel(cancel)
            storage_reserve(expected_rows * 512 + 16384, spill=True)
            durable_directory(out.parent)
            # A fresh name retains any interrupted temporary output as evidence.
            temporary = out.with_name(out.stem + "." + uuid4().hex + ".tmp.parquet")
            try:
                execute(
                    con,
                    "COPY (SELECT * FROM read_parquet(?,hive_partitioning=false)) TO ? (FORMAT PARQUET)",
                    [list(fragments), str(temporary)],
                    cancel=cancel,
                    progress=progress,
                    policy=policy,
                    stage="candidate_merge",
                )
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
                if out.exists():
                    raise ValueError("period_unowned_merged_candidate")
                os.replace(temporary, out)
            finally:
                storage_record(temporary)
                storage_record(out)
        sync_directory(out.parent)
        proof.update(phase="merged", version=file_version(out))
        _save_fragment_proof(cp, proof)
        progress(
            {
                "stage": "candidate_merged",
                "period": period,
                "expected_rows": expected_rows,
            }
        )
    if proof.get("version") != file_version(out):
        raise ValueError("period_validated_candidate_changed")
    return out, proof


def _candidate_receipts(
    con, periods, work, root, freq, cancel, progress, policy=DEFAULT_POLICY
):
    files, existing, pending, bindings, proofs, targets = [], {}, [], {}, {}, {}
    copied = read_json(work / "copy.json")
    expected_rows = copied["expected_rows"]
    for period in periods:
        check_cancel(cancel)
        # Validate period before deriving any run-scoped output/checkpoint path.
        targets[period] = target_path(root, freq, period)
        bindings[period] = fragments = _fragment_versions(work, period)
        for path in fragments:
            storage_record(path)
        cp = work / "validated" / f"{period}.json"
        if len(fragments) == 1:
            out = Path(next(iter(fragments)))
            proof = read_json(cp) if cp.exists() else None
            if proof is not None and "phase" in proof:
                raise ValueError("period_candidate_fragments_changed")
        else:
            out, proof = _merged_candidate(
                con,
                work,
                period,
                fragments,
                expected_rows[period],
                cancel,
                progress,
                policy,
            )
            proofs[period] = proof
        storage_record(out)
        files.append((period, out))
        if proof is not None and (
            "phase" not in proof or proof["phase"] == "validated"
        ):
            item = proof["item"]
            if (
                proof["receipt_hash"] != digest(item)
                or item["candidate"] != str(out)
                or item["version"] != file_version(out)
                or item["freq"] != freq
                or item["period"] != period
                or item["target"] != str(targets[period])
                or item["target_preimage"] != copied["target_preimages"][period]
            ):
                raise ValueError("period_validated_candidate_changed")
            existing[period] = item
        else:
            pending.append((period, out))
    facts = (
        _validate_candidates(
            con,
            pending,
            freq,
            cancel,
            progress,
            policy,
            fragments=[path for period, _ in pending for path in bindings[period]],
        )
        if pending
        else {}
    )
    receipts = []
    for index, (period, out) in enumerate(files):
        check_cancel(cancel)
        if (
            period not in existing
            and _fragment_versions(work, period) != bindings[period]
        ):
            raise ValueError("period_candidate_fragments_changed")
        item = existing.get(period)
        if item is None:
            item = {
                "freq": freq,
                "period": period,
                "candidate": str(out),
                "target_preimage": copied["target_preimages"][period],
                "target": str(targets[period]),
                **facts[str(out)],
            }
        if item["rows"] != expected_rows[period]:
            raise ValueError("period_candidate_row_reconciliation_failed")
        if period not in existing:
            proof = {"item": item, "receipt_hash": digest(item)}
            cp = work / "validated" / f"{period}.json"
            if period in proofs:
                _save_fragment_proof(
                    cp, {**proofs[period], **proof, "phase": "validated"}
                )
            else:
                atomic_json(cp, proof)
        receipts.append(item)
        progress(
            {
                "stage": "candidate_validated",
                "freq": freq,
                "completed": index + 1,
                "total": len(files),
            }
        )
    return receipts


def publish(item, *, checkpoint, con=None, cancel=lambda: False):
    """Replace succeeded/checkpoint failed recovers by the saved candidate's digest."""
    target = safe_path(item["target"])
    candidate = safe_path(item["candidate"])
    check_cancel(cancel)
    if checkpoint.exists():
        saved = read_json(checkpoint)
        if saved["sha256"] != item["sha256"] or saved["version"] != file_version(
            target
        ):
            raise ValueError("period_committed_file_changed")
        if any(
            saved.get(k) != item.get(k)
            for k in ("rows", "freq", "period", "target", "sha256", "source_asof")
        ):
            raise ValueError("period_checkpoint_identity_changed")
        with _AUDIT_LOCK:
            if len(_AUDITS) >= 4096:
                _AUDITS.pop(next(iter(_AUDITS)))
            _AUDITS[(str(target), tuple(saved["version"]))] = {
                k: saved[k] for k in ("rows", "version", "sha256")
            }
        return saved
    if (
        not candidate.exists()
        and target.exists()
        and file_version(target)[:4] == item["version"][:4]
        and file_digest(target) == item["sha256"]
    ):
        sync_directory(target.parent)
        storage_record(target)
        evidence = {
            "rows": item["rows"],
            "sha256": item["sha256"],
            "version": file_version(target),
        }
    else:
        if file_version(candidate) != item["version"]:
            raise ValueError("period_candidate_changed")
        if (
            "target_preimage" not in item
            or (file_version(target) if target.exists() else None)
            != item["target_preimage"]
        ):
            raise ValueError("period_target_preimage_changed")
        durable_directory(target.parent)
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("period_atomic_device_mismatch")
        check_cancel(cancel)
        storage_reserve()
        with candidate.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(candidate, target)
        budget = _BUDGET.get()
        if budget is not None:
            budget.moved(candidate, target)
        sync_directory(target.parent)
        version = file_version(target)
        if version[:4] != item["version"][:4]:
            raise ValueError("period_promoted_file_identity_changed")
        evidence = {"rows": item["rows"], "sha256": item["sha256"], "version": version}
    with _AUDIT_LOCK:
        if len(_AUDITS) >= 4096:
            _AUDITS.pop(next(iter(_AUDITS)))
        _AUDITS[(str(target), tuple(evidence["version"]))] = dict(evidence)
    saved = {**item, **evidence}
    atomic_json(checkpoint, saved)
    return saved


# Schema/key/range facts are shared by the three blocking checks only for this exact file version.
_AUDITS = {}
_AUDIT_LOCK = threading.Lock()


def audit_file(root, freq, period):
    import tempfile

    path = target_path(root, freq, period)
    version = file_version(path)
    key = (str(path), tuple(version))
    with _AUDIT_LOCK:
        if key in _AUDITS:
            return dict(_AUDITS[key])
        settings = DuckDBConnectionSettings(
            temp_directory=Path(tempfile.gettempdir()).resolve(),
            memory_limit=DEFAULT_POLICY.duckdb_memory,
            threads=DEFAULT_POLICY.duckdb_threads,
        )
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as con:
            evidence = validate_file(con, path, freq, period)
        if evidence["version"] != version:
            raise ValueError("period_file_changed")
        if len(_AUDITS) >= 4096:
            _AUDITS.pop(next(iter(_AUDITS)))
        _AUDITS[key] = evidence
        return dict(evidence)
