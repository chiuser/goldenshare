"""Columnar Raw candidates and one-file promotion for a frozen recovery plan."""

from __future__ import annotations

import json
import os
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    COLUMNS,
    TYPES,
    bounded_path,
    literal,
    parquet,
    records,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import literal_list


def file_key(freq, day):
    return f"{freq}_{day}"


def fingerprint(path):
    stat = Path(path).stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def inspect_relation(c, relation, freq, day):
    observed = {
        r[0]: r[1] for r in c.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    }
    if observed != TYPES or tuple(observed) != COLUMNS:
        raise ValueError("Candidate schema differs from formal Raw contract")
    # Same null/negative-value semantics as formal Raw checks; exchange may be null.
    values = ["open", "close", "high", "low", "vol", "amount", "vwap"]
    invalid_values = " OR ".join(f"{k} IS NULL OR {k}<0" for k in values)
    row = c.execute(f"""SELECT count(*),count(*)-count(DISTINCT(ts_code,trade_time)),
        count(*) FILTER(WHERE ts_code IS NULL OR trim(ts_code)='' OR trade_time IS NULL OR freq IS NULL
            OR freq<>{int(freq)} OR CAST(trade_time AS DATE)<>DATE {literal(day)} OR {invalid_values}),
        bit_xor(hash({",".join(COLUMNS)})),sum(hash({",".join(COLUMNS)})::HUGEINT)
        FROM {relation}""").fetchone()
    if row[0] <= 0 or row[1] or row[2]:
        raise ValueError(
            f"Raw candidate contract failed: rows/duplicates/invalid={row[:3]}"
        )
    return {"rows": row[0], "hash_xor": row[3], "hash_sum": str(row[4])}


def build_candidate(run, file, *, cancelled=lambda: False):
    freq, day = file["freq"], str(file["trade_date"])
    target = run.target(freq, day)
    if str(target) != file["target"]:
        raise ValueError("File target differs from frozen scope")
    key = file_key(freq, day)
    state = run.state("files", key)
    if state and state["status"] in ("validated", "promoting", "promoted"):
        return state
    if cancelled():
        raise InterruptedError("Cancelled before candidate")
    if not target.is_file():
        raise FileNotFoundError("Existing Raw partition required by this recovery plan")
    resolution_paths = []
    for window_id in file["window_ids"]:
        window = run.state("windows", window_id)
        if not window or window["status"] != "complete":
            raise ValueError(f"File sources not closed: {key}/{window_id}")
        resolution_paths.append(bounded_path(window["path"], run.root))
    candidate = bounded_path(
        run.root
        / "candidates"
        / f"freq={freq}"
        / f"trade_date={day}"
        / "part-000.parquet",
        run.root,
    )
    prior = fingerprint(target)
    with run.db(files=[target]) as c:
        c.execute(f"""CREATE TABLE scopes AS SELECT scope_id,latest_ts_code,source_candidates,freq,trade_date
            FROM read_parquet({literal(run.plan_dir / "scope.parquet")}) WHERE freq={freq} AND trade_date=DATE {literal(day)}""")
        c.execute(f"""CREATE TABLE resolved AS SELECT r.* FROM read_parquet({literal_list(resolution_paths)},hive_partitioning=false) r
            JOIN scopes USING(scope_id)""")
        count, unique, bad = c.execute(f"""SELECT count(*),count(DISTINCT scope_id),
            count(*) FILTER(WHERE status<>'source-ready' OR plan_hash<>{literal(run.hash)}) FROM resolved""").fetchone()
        if count != file["scope_count"] or unique != count or bad:
            raise ValueError(
                "All file members must be source-ready; unresolved residuals cannot be silently skipped"
            )
        if c.execute("""SELECT count(*) FROM resolved r JOIN scopes s USING(scope_id)
                WHERE r.freq<>s.freq OR r.trade_date<>s.trade_date OR r.latest_ts_code<>s.latest_ts_code
                   OR r.source_ts_code IS NULL OR NOT list_contains(s.source_candidates,r.source_ts_code)""").fetchone()[
            0
        ]:
            raise ValueError("Resolution outside the exact business scope")
        paths = [
            bounded_path(r[0], run.root)
            for r in c.execute("SELECT DISTINCT unnest(paths) FROM resolved").fetchall()
        ]
        if not paths:
            raise ValueError("Ready source has no payload")
        c.execute(f"""CREATE TABLE repairs AS SELECT p.* FROM read_parquet({literal_list(paths)},hive_partitioning=false) p
            JOIN resolved r ON p.ts_code=r.source_ts_code AND p.freq=r.freq AND CAST(p.trade_time AS DATE)=r.trade_date""")
        inspect_relation(c, "repairs", freq, day)
        # The frozen audit contains whole-stock-day gaps only. Do not apply this plan to partial-field repairs.
        c.execute(
            f"CREATE TABLE original AS SELECT {','.join(COLUMNS)} FROM read_parquet({literal(target)},hive_partitioning=false)"
        )
        if c.execute(
            """SELECT count(*) FROM original o JOIN scopes s ON list_contains(s.source_candidates,o.ts_code)"""
        ).fetchone()[0]:
            raise ValueError(
                "Frozen whole-day gap already contains source rows; do not overwrite or duplicate aliases"
            )
        c.execute("""CREATE TABLE merged AS SELECT o.* FROM original o ANTI JOIN repairs r
                     ON o.ts_code=r.ts_code AND o.trade_time=r.trade_time UNION ALL SELECT * FROM repairs""")
        expected = inspect_relation(c, "merged", freq, day)
        # Exact pair join above excludes bridge days. All original rows survive the merge unchanged.
        old_count, repair_count = c.execute(
            "SELECT (SELECT count(*) FROM original),(SELECT count(*) FROM repairs)"
        ).fetchone()
        if expected["rows"] != old_count + repair_count:
            raise ValueError("Unexpected modification outside audited whole-day gaps")
        if cancelled():
            raise InterruptedError("Cancelled before candidate output")
        parquet(
            c,
            f"SELECT {','.join(COLUMNS)} FROM merged ORDER BY ts_code,trade_time",
            candidate,
        )
        run.checkpoint(
            "files",
            key,
            status="generated",
            target=str(target),
            candidate=str(candidate),
        )
        if candidate.stat().st_size > run.budget["candidate_bytes"]:
            raise ValueError("Candidate exceeds byte budget; retained for diagnosis")
        actual = inspect_relation(
            c, f"read_parquet({literal(candidate)},hive_partitioning=false)", freq, day
        )
        if actual != expected:
            raise ValueError("Serialized candidate differs from validated merge")
        changes = run.root / "changes" / f"{key}.parquet"
        parquet(
            c,
            f"""SELECT {literal(run.hash)} plan_hash,r.latest_ts_code,r.source_ts_code,p.freq,
            CAST(p.trade_time AS DATE) trade_date,p.trade_time,'tushare_native' provenance
            FROM repairs p JOIN resolved r ON p.ts_code=r.source_ts_code
            AND p.freq=r.freq AND CAST(p.trade_time AS DATE)=r.trade_date ORDER BY p.ts_code,p.trade_time""",
            changes,
        )
    if fingerprint(target) != prior:
        raise ValueError("Target changed during candidate build")
    return run.checkpoint(
        "files",
        key,
        status="validated",
        target=str(target),
        candidate=str(candidate),
        target_before=prior,
        candidate_fingerprint=fingerprint(candidate),
        validation=actual,
        changes=str(changes),
        repair_rows=repair_count,
        existing_rows=old_count,
    )


def promote_candidate(run, file, *, cancelled=lambda: False):
    key = file_key(file["freq"], str(file["trade_date"]))
    target = run.target(file["freq"], str(file["trade_date"]))
    state = run.state("files", key)
    if not state or state["status"] not in ("validated", "promoting", "promoted"):
        raise ValueError("No validated candidate checkpoint")
    if state["target"] != str(target) or file["target"] != str(target):
        raise ValueError("Promotion target mismatch")
    candidate = bounded_path(state["candidate"], run.root)
    if state["status"] == "promoted":
        return state
    if cancelled():
        raise InterruptedError("Cancelled before promotion")
    if state["status"] == "promoting" and not candidate.exists():
        if fingerprint(target) != state["candidate_fingerprint"]:
            raise ValueError("Interrupted promotion cannot be reconciled")
    else:
        if (
            fingerprint(target) != state["target_before"]
            or fingerprint(candidate) != state["candidate_fingerprint"]
        ):
            raise ValueError("Candidate or target changed after validation")
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("Promotion requires the same filesystem")
        state = run.checkpoint(
            "files",
            key,
            **{k: v for k, v in state.items() if k not in ("plan_hash", "status")},
            status="promoting",
        )
        if cancelled():
            raise InterruptedError("Cancelled before atomic replace")
        os.replace(candidate, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    # Atomic rename preserves the already-validated bytes. Verify physical identity and footer after promotion.
    if fingerprint(target) != state["candidate_fingerprint"]:
        raise ValueError("Promoted file fingerprint differs from validated candidate")
    with run.db(files=[target]) as c:
        rows = c.execute(
            "SELECT num_rows FROM parquet_file_metadata(?)", [str(target)]
        ).fetchone()[0]
        if rows != state["validation"]["rows"]:
            raise ValueError("Post-promotion footer row count mismatch")
    return run.checkpoint(
        "files",
        key,
        **{k: v for k, v in state.items() if k not in ("plan_hash", "status")},
        status="promoted",
    )


def compact_changed_raw(run):
    paths = []
    for checkpoint in sorted((run.root / "files").glob("*.json")):
        state = json.loads(checkpoint.read_text())
        if state["plan_hash"] != run.hash:
            raise ValueError("Mixed plans in file checkpoints")
        if state["status"] == "promoted":
            paths.append(bounded_path(state["changes"], run.root))
    if paths:
        with run.db() as c:
            parquet(
                c,
                f"SELECT * FROM read_parquet({literal_list(paths)},hive_partitioning=false)",
                run.root / "actual-changed-raw.parquet",
            )


def selected_files(run, freq, limit, *, require_candidate=False):
    if freq not in run.plan["freqs"] or not 1 <= limit <= run.budget["file_batch"]:
        raise ValueError("Invalid file batch")
    with run.db() as c:
        files = records(
            c,
            f"SELECT * FROM read_parquet({literal(run.plan_dir / 'file-plan.parquet')}) WHERE freq=? ORDER BY trade_date",
            [freq],
        )
    eligible = set()
    resolution_index = run.root / "raw-resolution.parquet"
    if resolution_index.exists():
        with run.db() as c:
            rows = c.execute(
                f"""SELECT s.freq,s.trade_date FROM read_parquet({literal(run.plan_dir / "scope.parquet")}) s
                LEFT JOIN read_parquet({literal(resolution_index)}) r USING(scope_id)
                WHERE s.freq=? GROUP BY s.freq,s.trade_date
                HAVING count(*)=count(DISTINCT s.scope_id)
                   AND count(*) FILTER(WHERE r.status='source-ready' AND r.plan_hash={literal(run.hash)})=count(*)""",
                [freq],
            ).fetchall()
            eligible = {(f, str(d)) for f, d in rows}
    selected = []
    size = 0
    for file in files:
        state = run.state("files", file_key(freq, str(file["trade_date"])))
        if state and state["status"] == "promoted":
            continue
        if not state or state["status"] not in ("validated", "promoting"):
            if require_candidate or (freq, str(file["trade_date"])) not in eligible:
                continue
            windows = [run.state("windows", key) for key in file["window_ids"]]
            if any(not w or w["status"] != "complete" for w in windows):
                continue
        if size + file["existing_bytes"] > run.budget["candidate_bytes"]:
            if not selected:
                raise ValueError("Single input file exceeds batch byte budget")
            break
        selected.append(file)
        size += file["existing_bytes"]
        if len(selected) == limit:
            break
    return selected
