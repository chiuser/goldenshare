"""Merge sealed computed additions into Raw, preserving every existing record."""

from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_gap_aggregation_plan import (
    stage_path,
    verify_plan,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    BUDGET,
    COLUMNS,
    RecoveryRun,
    bounded_path,
    connection,
    file_digest,
    literal,
    parquet,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import (
    compact_changed_raw,
    file_key,
    fingerprint,
    inspect_relation,
    promote_candidate,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


class AggregationRawRun(RecoveryRun):
    """Reuse the recovery file checkpoint protocol with a distinct calculation plan."""

    def __init__(self, plan_path, scope, lake=DEFAULT_LAKE_ROOT):
        self.plan_path = stage_path(plan_path)
        self.plan_dir = self.plan_path.parent
        self.plan = verify_plan(self.plan_path)
        self.hash = self.plan["hash"]
        self.scope = Path(scope).absolute()
        if file_digest(self.scope) != self.plan["scope_sha"]:
            raise ValueError(
                "Original recovery scope differs from sealed aggregation scope"
            )
        self.root = stage_path(self.plan_dir / "raw-promotion")
        self.lake = Path(lake).absolute()
        self.budget = BUDGET
        self.initialize()

    def db(self, files=()):
        return connection(
            self.root,
            files=[self.scope, *files],
            directories=[self.plan_dir],
            budget=self.budget,
        )

    def selected(self):
        with self.db() as c:
            rows = c.execute(
                "SELECT freq,trade_date::VARCHAR,count(*) FROM read_parquet(?,hive_partitioning=false) GROUP BY freq,trade_date ORDER BY trade_date,freq",
                [str(self.plan_dir / "missing.parquet")],
            ).fetchall()
        return [
            {
                "freq": f,
                "trade_date": d,
                "repair_rows": n,
                "target": str(self.target(f, d)),
            }
            for f, d, n in rows
        ]


def build_raw(run, file, *, cancelled=lambda: False):
    freq, day = file["freq"], file["trade_date"]
    key = file_key(freq, day)
    state = run.state("files", key)
    if state and state["status"] in ("validated", "promoting", "promoted"):
        return state
    if cancelled():
        raise InterruptedError("Cancelled before merge")
    target = run.target(freq, day)
    if (
        str(target) != file["target"]
        or target.stat().st_size > run.budget["candidate_bytes"]
    ):
        raise ValueError("Target outside scope or byte budget")
    source = run.plan_dir / "additions" / day
    complete = json.loads((source / "complete.json").read_text())
    if complete["plan_hash"] != run.hash:
        raise ValueError("Addition plan mismatch")
    for name, sha in complete["artifacts"].items():
        if file_digest(bounded_path(source / name, run.plan_dir)) != sha:
            raise ValueError("Addition artifact changed")
    prior = fingerprint(target)
    candidate = run.root / "candidates" / f"{key}.parquet"
    changes = run.root / "changes" / f"{key}.parquet"
    with run.db(files=[target]) as c:
        for table, path in [
            ("repairs", source / "rows.parquet"),
            ("lineage", source / "lineage.parquet"),
            ("missing", run.plan_dir / "missing.parquet"),
        ]:
            c.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE freq=? AND trade_time::DATE=?",
                [str(path), freq, day],
            )
        check = inspect_relation(c, "repairs", freq, day)
        if check["rows"] != file["repair_rows"]:
            raise ValueError("Repair count differs from sealed missing keys")
        difference = c.execute("""SELECT count(*) FROM ((SELECT scope_id,trade_time FROM lineage EXCEPT ALL SELECT scope_id,trade_time FROM missing)
          UNION ALL (SELECT scope_id,trade_time FROM missing EXCEPT ALL SELECT scope_id,trade_time FROM lineage))""").fetchone()[
            0
        ]
        joined = c.execute(
            "SELECT count(*) FROM repairs JOIN lineage USING(ts_code,freq,trade_time)"
        ).fetchone()[0]
        if difference or joined != check["rows"]:
            raise ValueError("Addition keys differ from lineage/missing")
        c.execute(
            f"CREATE TABLE original AS SELECT {','.join(COLUMNS)} FROM read_parquet(?,hive_partitioning=false)",
            [str(target)],
        )
        overlaps = c.execute(
            """SELECT count(*) FROM original o JOIN lineage l ON o.trade_time=l.trade_time
          JOIN read_parquet(?,hive_partitioning=false) s USING(scope_id)
          WHERE list_contains(s.source_candidates,o.ts_code)""",
            [str(run.scope)],
        ).fetchone()[0]
        if overlaps:
            raise ValueError(
                "Existing Raw key or identity alias overlaps additions; no overwrite allowed"
            )
        old = c.execute("SELECT count(*) FROM original").fetchone()[0]
        c.execute(
            "CREATE TABLE merged AS SELECT * FROM original UNION ALL SELECT * FROM repairs"
        )
        expected = inspect_relation(c, "merged", freq, day)
        if expected["rows"] != old + check["rows"]:
            raise ValueError("Original rows not preserved")
        if cancelled():
            raise InterruptedError("Cancelled before candidate output")
        parquet(
            c,
            f"SELECT {','.join(COLUMNS)} FROM merged ORDER BY ts_code,trade_time",
            candidate,
        )
        if candidate.stat().st_size > run.budget["candidate_bytes"]:
            raise ValueError("Candidate exceeds byte budget")
        actual = inspect_relation(
            c, f"read_parquet({literal(candidate)},hive_partitioning=false)", freq, day
        )
        if actual != expected:
            raise ValueError("Serialized merge differs")
        parquet(
            c,
            f"""SELECT {literal(run.hash)} plan_hash,latest_ts_code,ts_code source_ts_code,freq,
          trade_time::DATE trade_date,trade_time,'aggregated' provenance,rule,input_paths FROM lineage""",
            changes,
        )
    if fingerprint(target) != prior:
        raise ValueError("Target changed during merge")
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
        repair_rows=check["rows"],
        existing_rows=old,
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["build", "promote"])
    p.add_argument("--plan", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args(argv)
    if not 1 <= a.limit <= 20:
        raise ValueError("Select 1 to 20 files")
    run = AggregationRawRun(a.plan, a.scope)
    run.require_operational_roots()
    stop = False

    def cancel(*_):
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, cancel)
    count = 0
    for file in run.selected():
        state = run.state("files", file_key(file["freq"], file["trade_date"]))
        if state and (
            state["status"] == "promoted"
            or (a.action == "build" and state["status"] in ("validated", "promoting"))
        ):
            continue
        if stop or count >= a.limit:
            break
        result = (build_raw if a.action == "build" else promote_candidate)(
            run, file, cancelled=lambda: stop
        )
        print(
            json.dumps(
                {
                    "freq": file["freq"],
                    "day": file["trade_date"],
                    "status": result["status"],
                    "rows": result["repair_rows"],
                }
            ),
            flush=True,
        )
        count += 1
    if a.action == "promote":
        compact_changed_raw(run)


if __name__ == "__main__":
    main()
