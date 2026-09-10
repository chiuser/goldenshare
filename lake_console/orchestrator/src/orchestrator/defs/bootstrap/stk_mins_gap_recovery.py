"""Frozen, bounded plans for stock-minute Raw recovery; no Dagster execution."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Timer

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_mins_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_STK_MINS_SCHEMA

VERSION = 1
START, END = "2014-01-01", "2026-09-09"
FREQS = (1, 5, 15, 30, 60)
COLUMNS = tuple(c.name for c in RAW_STK_MINS_SCHEMA)
TYPES = {c.name: c.type for c in RAW_STK_MINS_SCHEMA}
# These are frozen into plan.json; consumers use the frozen values.
BUDGET = {
    "min_free_disk_bytes": 200 * 1024**3,
    "memory_limit": "2GB",
    "threads": 2,
    "rss_bytes": 4 * 1024**3,
    "query_timeout_seconds": 300,
    "page_limit": 8000,
    "max_pages": 4,
    "attempts": 3,
    "requests_per_minute": 180,
    "source_batch": 200,
    "file_batch": 20,
    "candidate_bytes": 2 * 1024**3,
    "window_days": {"1": 20, "5": 100, "15": 240, "30": 240, "60": 240},
    "rows_per_day": {"1": 271, "5": 55, "15": 19, "30": 10, "60": 6},
    "bridge_days": 5,
}


def literal(value):
    return duckdb_string(str(value))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    with pending.open("w") as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(pending, path)


def bounded_path(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    if ".." in path.parts or not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path outside allowed root: {path}")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Symlink prohibited: {part}")
    return path


def check_unit(freq, day):
    if (
        freq not in FREQS
        or not START <= str(day) <= END
        or date.fromisoformat(str(day)).isoformat() != str(day)
    ):
        raise ValueError(f"Outside frozen date/frequency boundary: {freq}/{day}")


def records(connection, sql, params=None):
    cursor = connection.execute(sql, params or [])
    names = [x[0] for x in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def parquet(connection, sql, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending.parquet")
    connection.execute(
        f"COPY ({sql}) TO {literal(pending)} (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    with pending.open("rb") as f:
        os.fsync(f.fileno())
    os.replace(pending, path)


@contextmanager
def connection(root, *, files=(), directories=(), budget=None):
    budget = budget or BUDGET
    root = Path(root).resolve()
    settings = DuckDBConnectionSettings(
        temp_directory=root,
        max_temp_directory_size="0B",
        memory_limit=budget["memory_limit"],
        threads=budget["threads"],
    )
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as c:
        c.execute(
            "SET allowed_directories=?",
            [[str(root) + "/", *[str(Path(p).resolve()) + "/" for p in directories]]],
        )
        c.execute("SET allowed_paths=?", [[str(Path(p).absolute()) for p in files]])
        c.execute("SET enable_external_access=false")
        timer = Timer(budget["query_timeout_seconds"], c.interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield c
        finally:
            timer.cancel()


def rss_guard(budget):
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024
    if rss > budget["rss_bytes"]:
        raise RuntimeError(f"RSS limit exceeded: {rss}")


def freeze_plan(
    *, draft, audit, output, run_root, lake_root=Path(DEFAULT_LAKE_ROOT), seed_inputs=()
):
    """Read existing audit artifacts only. Write immutable planning artifacts."""
    draft, audit, output = (
        Path(draft).resolve(),
        Path(audit).resolve(),
        Path(output).absolute(),
    )
    if output.exists():
        raise FileExistsError("Use the existing frozen plan; do not overwrite it.")
    if not output.is_relative_to(Path("/private/tmp")):
        raise ValueError("Planning output must be under /private/tmp.")
    bounded_path(output, Path("/private/tmp"))
    output.mkdir(parents=True)
    inputs = [
        draft,
        audit / "reference/calendar.parquet",
        audit / "inventory.json",
        *map(Path, seed_inputs),
    ]
    with connection(output, files=inputs) as c:
        c.execute(f"CREATE TABLE draft AS SELECT * FROM read_parquet({literal(draft)})")
        invalid = c.execute(f"""SELECT count(*) FROM draft WHERE freq NOT IN (1,5,15,30,60)
            OR freq IS NULL OR trade_date IS NULL OR trade_date < DATE '{START}' OR trade_date > DATE '{END}'
            OR latest_ts_code IS NULL OR NOT regexp_full_match(latest_ts_code, '[0-9]{{6}}\\.(SH|SZ|BJ)')
            OR source_candidates IS NULL OR len(source_candidates)=0 OR len(source_candidates)>2
            OR (NOT unconfirmed AND (missing_grid_count<>expected_grid_count OR missing_grid_count IS NULL))""").fetchone()[
            0
        ]
        if invalid:
            raise ValueError(f"Invalid scope units: {invalid}")
        n, unique = c.execute(
            "SELECT count(*),count(DISTINCT (latest_ts_code,freq,trade_date)) FROM draft"
        ).fetchone()
        if not n or n != unique:
            raise ValueError("Empty or duplicate business scope")
        # One source may have several aliases; it must never identify two issuers on the same day.
        conflict = c.execute("""SELECT count(*) FROM (SELECT trade_date,src FROM draft,
            unnest(source_candidates) a(src) GROUP BY trade_date,src HAVING count(DISTINCT latest_ts_code)>1)""").fetchone()[
            0
        ]
        if conflict:
            raise ValueError("A source code maps to multiple business identities")
        c.execute(f"""CREATE TABLE cal AS SELECT trade_date, row_number() OVER(ORDER BY trade_date) idx
            FROM read_parquet({literal(inputs[1])}) WHERE trade_date BETWEEN DATE '{START}' AND DATE '{END}'""")
        if c.execute(
            "SELECT count(*) FROM draft ANTI JOIN cal USING(trade_date)"
        ).fetchone()[0]:
            raise ValueError("Scope contains non-calendar date")
        c.execute("""CREATE TABLE units AS SELECT d.*, cal.idx,
            md5(array_to_string(list_sort(source_candidates), ',')) candidate_key
            FROM draft d JOIN cal USING(trade_date)""")
        # Python only plans compact date windows, streaming at most 4096 records.
        cursor = c.execute("""SELECT latest_ts_code,freq,candidate_key,source_candidates,trade_date,idx
            FROM units ORDER BY latest_ts_code,freq,candidate_key,trade_date""")
        windows_path = output / "windows.jsonl"
        count = 0
        window = None

        def finish(w, stream):
            nonlocal count
            if w is None:
                return
            w["window_id"] = digest(w)[:24]
            w["estimated_rows"] = (w["last_idx"] - w["first_idx"] + 1) * BUDGET[
                "rows_per_day"
            ][str(w["freq"])]
            if w["estimated_rows"] >= 6000:
                raise ValueError("Window estimate exceeds budget")
            stream.write(json.dumps(w, default=str) + "\n")
            count += 1

        with windows_path.open("w") as stream:
            while batch := cursor.fetchmany(4096):
                for code, freq, key, candidates, day, idx in batch:
                    group = (code, freq, key)
                    if window and (
                        group
                        != (
                            window["latest_ts_code"],
                            window["freq"],
                            window["candidate_key"],
                        )
                        or idx - window["first_idx"] + 1
                        > BUDGET["window_days"][str(freq)]
                        or idx - window["last_idx"] > BUDGET["bridge_days"] + 1
                    ):
                        finish(window, stream)
                        window = None
                    if window is None:
                        ordered = sorted(candidates, key=lambda x: (x != code, x))
                        window = {
                            "latest_ts_code": code,
                            "freq": freq,
                            "candidate_key": key,
                            "candidates": ordered,
                            "start_date": str(day),
                            "end_date": str(day),
                            "first_idx": idx,
                            "last_idx": idx,
                            "scope_count": 0,
                        }
                    window["scope_count"] += 1
                    window.update(end_date=str(day), last_idx=idx)
            finish(window, stream)
        c.execute(
            f"CREATE TABLE windows AS SELECT * FROM read_json_auto({literal(windows_path)},format='newline_delimited')"
        )
        parquet(
            c,
            """SELECT w.window_id,d.scope_id,d.latest_ts_code,d.source_candidates,
             d.freq,d.trade_date,d.evidence,d.unconfirmed,d.expected_grid_count,d.missing_grid_count,d.present_grid,d.idx
             FROM units d JOIN windows w ON d.latest_ts_code=w.latest_ts_code AND d.freq=w.freq
             AND d.candidate_key=w.candidate_key AND d.idx BETWEEN w.first_idx AND w.last_idx
             ORDER BY window_id,trade_date""",
            output / "scope.parquet",
        )
        if (
            c.execute(
                f"SELECT count(*) FROM read_parquet({literal(output / 'scope.parquet')})"
            ).fetchone()[0]
            != n
        ):
            raise ValueError("Window membership mismatch")
        parquet(
            c,
            "SELECT * FROM windows ORDER BY freq,start_date,latest_ts_code",
            output / "source-windows.parquet",
        )
        c.execute(
            f"CREATE TABLE inventory AS SELECT * FROM read_json_auto({literal(inputs[2])})"
        )
        scope = f"read_parquet({literal(output / 'scope.parquet')})"
        parquet(
            c,
            f"""SELECT s.freq,s.trade_date,count(*) scope_count,list(DISTINCT window_id ORDER BY window_id) window_ids,
            {literal(lake_root)}||'/raw/tushare/stk_mins/freq='||s.freq||'/trade_date='||s.trade_date||'/part-000.parquet' AS "target",
            max(i.size_bytes) existing_bytes
            FROM {scope} s LEFT JOIN inventory i ON i.freq=s.freq AND CAST(i.trade_date AS DATE)=s.trade_date
            GROUP BY s.freq,s.trade_date ORDER BY s.freq,s.trade_date""",
            output / "file-plan.parquet",
        )
        counts = records(
            c,
            f"""SELECT freq,count(*) units,count(*) FILTER(WHERE NOT unconfirmed) confirmed,
            count(*) FILTER(WHERE unconfirmed) unconfirmed FROM {scope} GROUP BY freq ORDER BY freq""",
        )
        file_count, missing_files = c.execute(
            f"SELECT count(*),count(*) FILTER(WHERE existing_bytes IS NULL) FROM read_parquet({literal(output / 'file-plan.parquet')})"
        ).fetchone()
        if missing_files:
            raise ValueError("Audit inventory does not cover all target files")
    plan = {
        "version": VERSION,
        "start": START,
        "end": END,
        "freqs": list(FREQS),
        "lake_root": str(lake_root),
        "run_root": str(run_root),
        "budget": BUDGET,
        "source_fields": list(COLUMNS),
        "raw_schema": TYPES,
        "unit_count": n,
        "window_count": count,
        "file_count": file_count,
        "counts": counts,
        "inputs": [{"path": str(p), "sha256": file_digest(p)} for p in inputs],
        "seed_inputs": list(map(str, seed_inputs)),
        "artifacts": {p.name: file_digest(p) for p in output.glob("*.parquet")},
        "stage": "raw_only",
        "source_policy": "cached_then_latest_then_valid_alias_on_missing",
        "business_identity": "latest_ts_code",
        "raw_identity": "source_ts_code",
    }
    plan["plan_hash"] = digest(plan)
    atomic_json(output / "plan.json", plan)
    return plan


class RecoveryRun:
    def __init__(self, plan_path, expected_hash):
        self.plan_path = Path(plan_path).resolve()
        self.plan_dir = self.plan_path.parent
        self.plan = json.loads(self.plan_path.read_text())
        claimed = self.plan.pop("plan_hash")
        if (
            claimed != expected_hash
            or claimed != digest(self.plan)
            or self.plan["version"] != VERSION
        ):
            raise ValueError("Plan hash/version mismatch")
        self.plan["plan_hash"] = claimed
        self.hash = claimed
        self.root = Path(self.plan["run_root"]).absolute()
        self.lake = Path(self.plan["lake_root"]).absolute()
        self.budget = self.plan["budget"]
        if (
            self.budget != BUDGET
            or self.plan["source_fields"] != list(COLUMNS)
            or self.plan["raw_schema"] != TYPES
        ):
            raise ValueError("Unreviewed budget or source contract")
        for name, fingerprint in self.plan["artifacts"].items():
            path = bounded_path(self.plan_dir / name, self.plan_dir)
            if file_digest(path) != fingerprint:
                raise ValueError(f"Frozen artifact changed: {name}")

    def require_operational_roots(self):
        if self.lake != Path(DEFAULT_LAKE_ROOT):
            raise ValueError("CLI requires the formal Lake root")
        bounded_path(self.root, Path(DEFAULT_LAKE_STAGING_ROOT))

    def initialize(self):
        if self.lake == Path(DEFAULT_LAKE_ROOT):
            self.require_operational_roots()
            parent = self.root.parent
            while not parent.exists():
                parent = parent.parent
            if shutil.disk_usage(parent).free < self.budget["min_free_disk_bytes"]:
                raise RuntimeError(
                    "Insufficient disk space for the reviewed source/candidate budget"
                )
        elif not self.lake.is_relative_to(Path("/private/tmp")):
            raise ValueError("Isolated roots must be under /private/tmp")
        if self.root == self.lake or self.root.is_relative_to(self.lake):
            raise ValueError("Execution root must be outside formal Lake")
        bounded_path(self.root, self.root.parent)
        self.root.mkdir(parents=True, exist_ok=True)
        identity = self.root / "run.json"
        if (
            identity.exists()
            and json.loads(identity.read_text())["plan_hash"] != self.hash
        ):
            raise ValueError("Execution directory belongs to another plan")
        if not identity.exists():
            atomic_json(
                identity, {"plan_hash": self.hash, "plan_path": str(self.plan_path)}
            )

    def db(self, files=()):
        rss_guard(self.budget)
        return connection(
            self.root, files=files, directories=[self.plan_dir], budget=self.budget
        )

    def state(self, kind, key):
        path = bounded_path(self.root / kind / (key + ".json"), self.root)
        if not path.exists():
            return None
        state = json.loads(path.read_text())
        if state["plan_hash"] != self.hash:
            raise ValueError("Checkpoint belongs to another plan")
        return state

    def checkpoint(self, kind, key, **values):
        value = dict(plan_hash=self.hash, **values)
        atomic_json(bounded_path(self.root / kind / (key + ".json"), self.root), value)
        with (self.root / "checkpoint.jsonl").open("a") as f:
            f.write(json.dumps(dict(kind=kind, key=key, **value), default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return value

    def target(self, freq, day):
        check_unit(freq, day)
        return bounded_path(
            raw_stk_mins_path(self.lake, freq, str(day)), self.lake / "raw"
        )
