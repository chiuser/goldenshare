"""Source-only columnar assembly and per-file atomic publication for period Raw."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
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


def atomic_json(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    safe_path(tmp)
    with tmp.open("w") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


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


def dataset_root(root, freq):
    return safe_path(
        Path(root) / "raw" / "tushare" / f"stk_period_bar_adj_{frequency(freq)}"
    )


def target_path(root, freq, period):
    period_date(period, freq)
    base = dataset_root(root, freq)
    return safe_path(
        base
        / (f"week_end={period}" if freq == "week" else f"month={period}")
        / ("part-000.parquet" if freq == "week" else "data.parquet")
    )


def connection(work, policy=DEFAULT_POLICY):
    return connect_configured_duckdb(
        DuckDBConnectionSettings(
            temp_directory=Path(work) / "spill",
            max_temp_directory_size=f"{policy.spill_bytes}B",
            memory_limit=policy.duckdb_memory,
            threads=policy.duckdb_threads,
        )
    )


def check_memory(policy):
    import resource
    import sys

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    if peak > policy.rss_bytes:
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
    check_cancel(cancel)
    check_memory(policy)
    import time

    errors = []
    stop = threading.Event()

    def watch():
        emitted = time.monotonic()
        while not stop.wait(0.2):
            try:
                check_memory(policy)
            except ValueError as error:
                errors.append(error)
                con.interrupt()
                return
            if cancel():
                con.interrupt()
                return
            if time.monotonic() - emitted >= policy.progress_seconds:
                progress(
                    {
                        "stage": stage,
                        "status": "working",
                        "business_completed_unchanged": True,
                    }
                )
                emitted = time.monotonic()

    monitor = threading.Thread(target=watch, daemon=True)
    monitor.start()
    try:
        parameters = list(parameters or [])
        # DuckDB COPY binds its filename before SELECT parameters; literalize only our guarded path.
        if sql.startswith("COPY ") and " TO ? " in sql:
            output = str(safe_path(parameters.pop()))
            sql = sql.replace(" TO ? ", " TO '" + output.replace("'", "''") + "' ", 1)
        result = con.execute(sql, parameters)
        if errors:
            raise errors[0]
        check_memory(policy)
        check_cancel(cancel)
        progress({"stage": stage})
        return result
    except Exception:
        if errors:
            raise errors[0]
        check_cancel(cancel)
        raise
    finally:
        stop.set()
        monitor.join()


def validate_file(con, path, freq, period, *, cancel=lambda: False):
    before = file_version(path)
    schema = [
        tuple(r[:2])
        for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
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
    ).fetchone()
    if rows != unique or invalid or before != file_version(path):
        raise ValueError("period_file_key_or_partition_invalid")
    return {"rows": rows, "version": before, "sha256": file_digest(path)}


def _old_range_paths(allpaths, freq, codes, evidence):
    """Reuse exact compressed ranges only while the baseline's complete file inventory matches."""
    if not evidence or evidence.get("range_index_version") != VERSION:
        return None
    if evidence.get("range_index_hash") != digest(
        {k: evidence.get(k) for k in ("files", "stock_ranges")}
    ):
        return None
    files = [i for i in evidence.get("files", []) if i["freq"] == freq]
    if set(allpaths) != {i["target"] for i in files}:
        return None
    if any(i["version"] != file_version(i["target"]) for i in files):
        return None
    ranges = evidence.get("stock_ranges", {}).get(freq, {})
    return [
        (i["target"], i["period"])
        for i in files
        if any(
            first <= i["period"] <= last
            for code in codes
            for first, last in ranges.get(code, [])
        )
    ]


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
            con.execute(
                "CREATE TEMP TABLE incoming ("
                + ",".join(f'"{n}" {t}' for n, t in SPECS)
                + ",filename VARCHAR)"
            )
        if con.execute(
            "SELECT count(*) FROM incoming WHERE freq<>?", [freq]
        ).fetchone()[0]:
            raise ValueError("period_source_frequency_mixed")
        if (
            not con.execute("SELECT count(*) FROM incoming").fetchone()[0]
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
            for r in con.execute(
                "SELECT DISTINCT ts_code FROM incoming WHERE list_contains(?,filename)",
                [history_paths],
            ).fetchall()
        }
        if actual != set(codes) and mode != "bootstrap":
            raise ValueError("period_history_codes_mismatch")
        # Repeated keys across current/history snapshots may coalesce only as identical full rows.
        conflict = con.execute(
            f"SELECT ts_code,trade_date,freq FROM incoming GROUP BY 1,2,3 "
            f"HAVING count(DISTINCT ROW({COLUMNS}))>1 LIMIT 1"
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
            and con.execute(
                "SELECT count(*)-count(DISTINCT(ts_code,trade_date,freq)) FROM incoming"
            ).fetchone()[0]
        ):
            raise ValueError("period_source_duplicate_key")
        if mode == "upsert" and codes:
            absent = con.execute(
                "SELECT ts_code,trade_date,freq FROM incoming p WHERE list_contains(?,p.ts_code) "
                "AND NOT list_contains(?,p.filename) AND NOT EXISTS (SELECT 1 FROM incoming h "
                "WHERE list_contains(?,h.filename) AND h.ts_code=p.ts_code AND h.trade_date=p.trade_date AND h.freq=p.freq) LIMIT 1",
                [list(codes), history_paths, history_paths],
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
        con.execute(
            f"CREATE TEMP TABLE source AS SELECT DISTINCT {COLUMNS},{PERIOD_SQL} AS period FROM incoming"
        )
        selected = {
            r[0] for r in con.execute("SELECT DISTINCT period FROM source").fetchall()
        }
        if (
            mode == "upsert"
            and con.execute(
                f"SELECT count(*) FROM incoming WHERE NOT list_contains(?,filename) AND NOT list_contains(?,{PERIOD_SQL})",
                [history_paths, list(periods)],
            ).fetchone()[0]
        ):
            raise ValueError("period_source_scope_mismatch")
        oldpaths = []
        allpaths = None
        range_index_valid = mode == "bootstrap"
        reused = None
        if (
            mode != "bootstrap"
            and range_evidence
            and range_evidence.get("range_index_version") == VERSION
        ):
            allpaths = [
                str(safe_path(p)) for p in dataset_root(root, freq).glob("*/*.parquet")
            ]
            reused = _old_range_paths(
                allpaths, freq, set(codes) | set(retired_codes), range_evidence
            )
            range_index_valid = reused is not None
        if mode == "history" or (mode == "upsert" and (codes or retired_codes)):
            if allpaths is None:
                allpaths = [
                    str(safe_path(p))
                    for p in dataset_root(root, freq).glob("*/*.parquet")
                ]
            if reused is not None:
                affected = reused
                progress({"stage": "reuse_old_ranges", "files": len(affected)})
            elif allpaths:
                affected = execute(
                    con,
                    f"SELECT DISTINCT filename,{PERIOD_SQL} AS period FROM read_parquet(?,hive_partitioning=false,filename=true) WHERE list_contains(?,ts_code)",
                    [allpaths, sorted(set(codes) | set(retired_codes))],
                    cancel=cancel,
                    progress=progress,
                    stage="locate_old_keys",
                    policy=policy,
                ).fetchall()
            else:
                affected = []
            selected.update(r[1] for r in affected)
            oldpaths.extend(r[0] for r in affected)
        if mode != "bootstrap":
            oldpaths.extend(
                str(target_path(root, freq, p))
                for p in selected
                if target_path(root, freq, p).exists()
            )
            oldpaths = sorted(set(oldpaths))
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
            con.execute("CREATE TEMP TABLE old AS SELECT * FROM source WHERE false")
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
            con.execute("CREATE TEMP VIEW combined AS SELECT * FROM source")
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
                )
        atomic_json(
            copy_receipt,
            {
                "identity": identity,
                "periods": sorted(selected),
                "stock_ranges": _source_ranges(
                    con, freq, cancel=cancel, progress=progress, policy=policy
                ),
                "range_index_valid": range_index_valid,
                "expected_rows": {p: expected_rows.get(p, 0) for p in selected},
            },
        )
        return _candidate_receipts(
            con, sorted(selected), work, root, freq, cancel, progress, policy
        )


def _validate_candidates(con, pending, freq, cancel, progress, policy):
    paths = [str(path) for _, path in pending]
    versions = {str(path): file_version(path) for _, path in pending}
    schemas = execute(
        con,
        "SELECT file_name,list(name ORDER BY column_id),list(duckdb_type ORDER BY column_id) "
        "FROM parquet_schema(?) WHERE column_id>0 GROUP BY file_name",
        [paths],
        cancel=cancel,
        progress=progress,
        stage="candidate_schemas",
        policy=policy,
    ).fetchall()
    if len(schemas) != len(paths) or any(
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
        min({PERIOD_SQL}),max({PERIOD_SQL})
        FROM read_parquet(?,hive_partitioning=false,filename=true) GROUP BY filename""",
        [freq, paths],
        cancel=cancel,
        progress=progress,
        stage="candidate_facts",
        policy=policy,
    ).fetchall()
    facts = {
        path: (count, unique, invalid, first, last)
        for path, count, unique, invalid, first, last in rows
    }
    result = {}
    for period, path in pending:
        key = str(path)
        count, unique, invalid, first, last = facts.get(key, (0, 0, 0, None, None))
        if (
            count != unique
            or invalid
            or (count and (first != period or last != period))
            or versions[key] != file_version(path)
        ):
            raise ValueError("period_file_key_or_partition_invalid")
        result[key] = {
            "rows": count,
            "version": versions[key],
            "sha256": file_digest(path),
        }
    return result


def _candidate_receipts(
    con, periods, work, root, freq, cancel, progress, policy=DEFAULT_POLICY
):
    files, existing, pending = [], {}, []
    for period in periods:
        check_cancel(cancel)
        outputs = list((work / "outputs" / f"period={period}").glob("*.parquet"))
        if len(outputs) != 1:
            raise ValueError("period_candidate_file_count_invalid")
        out = outputs[0]
        files.append((period, out))
        cp = work / "validated" / f"{period}.json"
        if cp.exists():
            proof = read_json(cp)
            item = proof["item"]
            if (
                proof["receipt_hash"] != digest(item)
                or item["candidate"] != str(out)
                or item["version"] != file_version(out)
            ):
                raise ValueError("period_validated_candidate_changed")
            existing[period] = item
        else:
            pending.append((period, out))
    facts = (
        _validate_candidates(con, pending, freq, cancel, progress, policy)
        if pending
        else {}
    )
    expected_rows = read_json(work / "copy.json")["expected_rows"]
    receipts = []
    for index, (period, out) in enumerate(files):
        check_cancel(cancel)
        item = existing.get(period)
        if item is None:
            item = {
                "freq": freq,
                "period": period,
                "candidate": str(out),
                "target": str(target_path(root, freq, period)),
                **facts[str(out)],
            }
            atomic_json(
                work / "validated" / f"{period}.json",
                {"item": item, "receipt_hash": digest(item)},
            )
        if item["rows"] != expected_rows[period]:
            raise ValueError("period_candidate_row_reconciliation_failed")
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


def publish(item, *, checkpoint, con, cancel=lambda: False):
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
            for k in ("rows", "freq", "period", "target", "sha256")
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
        and file_digest(target) == item["sha256"]
    ):
        evidence = {
            "rows": item["rows"],
            "sha256": item["sha256"],
            "version": file_version(target),
        }
    else:
        if file_version(candidate) != item["version"]:
            raise ValueError("period_candidate_changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("period_atomic_device_mismatch")
        check_cancel(cancel)
        os.replace(candidate, target)
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
