"""Freeze exact missing minute keys without replacing native source records."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    COLUMNS,
    TYPES,
    atomic_json,
    bounded_path,
    check_unit,
    connection,
    digest,
    file_digest,
    literal,
    parquet,
    records,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import fingerprint
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import literal_list
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT

RULE = "raw_missing_keys_from_1min_v1"
BUDGET = {"memory_limit": "1GB", "threads": 2, "query_timeout_seconds": 300}
MAX_INPUT_BYTES = 512 * 1024**2


def stage_path(path):
    path = Path(path).absolute()
    roots = (Path(DEFAULT_LAKE_STAGING_ROOT), Path("/private/tmp"))
    for root in roots:
        if path.is_relative_to(root):
            return bounded_path(path, root)
    raise ValueError("Output must be staging or isolated /private/tmp")


def input_path(path):
    path = Path(path).absolute()
    roots = (
        Path(DEFAULT_LAKE_ROOT) / "raw",
        Path(DEFAULT_LAKE_STAGING_ROOT),
        Path("/private/tmp"),
    )
    for root in roots:
        if path.is_relative_to(root):
            return bounded_path(path, root)
    raise ValueError("Input is outside approved Raw/cache roots")


def raw_relation(paths):
    if paths:
        return f"SELECT {','.join(COLUMNS)} FROM read_parquet({literal_list(paths)},hive_partitioning=false)"
    return (
        "SELECT "
        + ",".join(f"NULL::{TYPES[k]} AS {k}" for k in COLUMNS)
        + " WHERE false"
    )


def grid_sql(table="tasks"):
    return f"""SELECT t.scope_id,t.latest_ts_code,t.freq,t.trade_date,
      t.trade_date::TIMESTAMP + m * INTERVAL '1 minute' trade_time
      FROM {table} t, LATERAL (
        SELECT 570 AS m UNION ALL SELECT unnest(range(570+t.freq,691,t.freq))
        UNION ALL SELECT unnest(range(780+t.freq,901,t.freq))) clocks"""


def core_bad(alias=""):
    a = alias + "." if alias else ""
    fields = ["open", "high", "low", "close", "vol"]
    terms = [f"({a}{k} IS NULL OR NOT isfinite({a}{k}) OR {a}{k}<0)" for k in fields]
    terms += [
        f"{a}high<{a}low",
        f"{a}open<{a}low",
        f"{a}open>{a}high",
        f"{a}close<{a}low",
        f"{a}close>{a}high",
    ]
    return "(" + " OR ".join(terms) + ")"


def verify_plan(path):
    path = stage_path(path)
    p = json.loads(path.read_text())
    if (
        p["rule"] != RULE
        or digest({k: v for k, v in p.items() if k != "hash"}) != p["hash"]
    ):
        raise ValueError("Invalid aggregation plan seal")
    for name, sha in p["artifacts"].items():
        if file_digest(bounded_path(path.parent / name, path.parent)) != sha:
            raise ValueError("Frozen aggregation artifact changed")
    return p


def freeze_missing_plan(manifest_path, scope_path, output, recovery_hash):
    """Manifest references prior whole-day Raw absence evidence and verified 1m sources."""
    manifest_path, scope_path = input_path(manifest_path), input_path(scope_path)
    output = stage_path(output)
    output.mkdir(parents=True, exist_ok=True)
    seal = output / "plan.json"
    if seal.exists():
        p = verify_plan(seal)
        if (
            p["manifest_sha"] != file_digest(manifest_path)
            or p["scope_sha"] != file_digest(scope_path)
            or p["recovery_hash"] != recovery_hash
        ):
            raise ValueError("Existing plan belongs to different inputs")
        return p
    tasks = json.loads(manifest_path.read_text())
    if (
        not tasks
        or len(tasks) > 10000
        or len({t["scope_id"] for t in tasks}) != len(tasks)
    ):
        raise ValueError("Empty, duplicate or oversized task selection")
    native_paths = set()
    inputs = {str(manifest_path), str(scope_path)}
    for t in tasks:
        check_unit(t["freq"], t["trade_date"])
        if t["freq"] == 1 or not t["one_paths"] or not t["one_code"]:
            raise ValueError("Only coarse gaps with a selected 1m source are allowed")
        for path in t["one_paths"] + t["native_paths"]:
            inputs.add(str(input_path(path)))
        native_paths.update(t["native_paths"])
    if sum(Path(p).stat().st_size for p in native_paths) > MAX_INPUT_BYTES:
        raise ValueError("Native evidence exceeds plan scan budget")
    with connection(output, files=sorted(inputs), budget=BUDGET) as c:
        c.execute(
            f"CREATE TABLE tasks AS SELECT * REPLACE(trade_date::DATE AS trade_date) FROM read_json_auto({literal(manifest_path)})"
        )
        c.execute(
            f"CREATE TABLE scope AS SELECT * FROM read_parquet({literal(scope_path)},hive_partitioning=false) WHERE scope_id IN (SELECT scope_id FROM tasks)"
        )
        if c.execute("SELECT count(*)<>count(DISTINCT scope_id) FROM scope").fetchone()[
            0
        ]:
            raise ValueError("Duplicate frozen scope identity")
        invalid = c.execute("""SELECT count(*) FROM tasks t LEFT JOIN scope s USING(scope_id)
            WHERE s.scope_id IS NULL OR t.latest_ts_code IS DISTINCT FROM s.latest_ts_code
            OR t.freq IS DISTINCT FROM s.freq OR t.trade_date IS DISTINCT FROM s.trade_date
            OR NOT coalesce(list_contains(s.source_candidates,t.one_code),false)
            OR s.missing_grid_count IS DISTINCT FROM s.expected_grid_count
            OR s.expected_grid_count IS DISTINCT FROM (240//t.freq+1)""").fetchone()[0]
        if invalid:
            raise ValueError("Task is outside frozen whole-day scope or identity")
        c.execute("CREATE TABLE expected AS " + grid_sql())
        c.execute("CREATE TABLE payload AS " + raw_relation(sorted(native_paths)))
        c.execute("""CREATE TABLE supplied AS SELECT t.scope_id,p.* FROM payload p
            JOIN scope s ON list_contains(s.source_candidates,p.ts_code) AND s.freq=p.freq AND s.trade_date=p.trade_time::DATE
            JOIN tasks t USING(scope_id)""")
        # Equivalent old/new source identities are one business key, not two bars.
        c.execute("CREATE TABLE native_evidence AS SELECT DISTINCT * FROM supplied")
        values = ",".join(k for k in COLUMNS if k != "ts_code")
        if c.execute(
            f"SELECT count(*) FROM (SELECT scope_id,trade_time FROM native_evidence GROUP BY ALL HAVING count(DISTINCT ({values}))>1)"
        ).fetchone()[0]:
            raise ValueError("Conflicting native values need explicit resolution")
        c.execute("""CREATE TABLE existing AS SELECT n.* FROM native_evidence n JOIN tasks t USING(scope_id)
            QUALIFY row_number() OVER(PARTITION BY n.scope_id,n.trade_time ORDER BY (n.ts_code=t.latest_ts_code) DESC,n.ts_code)=1""")
        c.execute("""CREATE TABLE missing AS SELECT e.*,t.one_code,t.one_paths FROM expected e
            JOIN tasks t USING(scope_id) ANTI JOIN existing n ON n.scope_id=e.scope_id AND n.trade_time=e.trade_time""")
        c.execute(f"""CREATE TABLE blocked AS SELECT n.*,'existing_invalid_core' reason FROM existing n
            JOIN expected e USING(scope_id,trade_time) WHERE {core_bad("n")}""")
        c.execute(
            """CREATE TABLE extras AS SELECT n.* FROM existing n ANTI JOIN expected e USING(scope_id,trade_time)"""
        )
        for name in [
            "tasks",
            "missing",
            "existing",
            "native_evidence",
            "blocked",
            "extras",
        ]:
            parquet(c, f"SELECT * FROM {name}", output / f"{name}.parquet")
        summary = records(
            c,
            """SELECT t.freq,count(*) scopes,sum(x.missing) missing_records,
            sum(x.missing>0) scopes_with_missing FROM tasks t JOIN
            (SELECT t.scope_id,count(m.trade_time) missing FROM tasks t LEFT JOIN missing m USING(scope_id) GROUP BY 1) x USING(scope_id)
            GROUP BY 1 ORDER BY 1""",
        )
        counts = {
            name: c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in ["expected", "missing", "existing", "blocked", "extras"]
        }
        if (
            counts["missing"] + counts["existing"] - counts["extras"]
            != counts["expected"]
        ):
            raise ValueError("Missing/native keys do not conserve expected grid")
    p = {
        "rule": RULE,
        "recovery_hash": recovery_hash,
        "manifest_sha": file_digest(manifest_path),
        "scope_sha": file_digest(scope_path),
        "summary": summary,
        "counts": counts,
        "inputs": {p: fingerprint(p) for p in sorted(inputs)},
        "artifacts": {p.name: file_digest(p) for p in output.glob("*.parquet")},
    }
    p["hash"] = digest(p)
    atomic_json(seal, p)
    return p
