"""Generate staging-only additions from a sealed exact-key plan; no promotion."""

from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_gap_aggregation_plan import (
    BUDGET,
    MAX_INPUT_BYTES,
    RULE,
    core_bad,
    freeze_missing_plan,
    input_path,
    raw_relation,
    stage_path,
    verify_plan,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    COLUMNS,
    RecoveryRun,
    atomic_json,
    check_unit,
    connection,
    file_digest,
    literal,
    parquet,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import fingerprint


def build_date(plan_path, day, *, cancelled=lambda: False):
    """One bounded date is independently committed and safe to replay after exit."""
    check_unit(5, day)
    plan_path = stage_path(plan_path)
    plan = verify_plan(plan_path)
    base = plan_path.parent
    destination = stage_path(base / "additions" / day)
    state_path = destination / "complete.json"
    if cancelled():
        raise InterruptedError("Cancelled before date")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state["plan_hash"] != plan["hash"]:
            raise ValueError("Completed date belongs to another plan")
        for name, sha in state["artifacts"].items():
            if file_digest(destination / name) != sha:
                raise ValueError("Completed candidate was changed")
        return state
    destination.mkdir(parents=True, exist_ok=True)
    with connection(base, budget=BUDGET) as c:
        paths = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT unnest(one_paths) FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=?",
                [str(base / "missing.parquet"), day],
            ).fetchall()
        ]
    if not paths:
        raise ValueError("No missing records for selected date")
    for path in paths:
        input_path(path)
        if fingerprint(path) != plan["inputs"].get(path):
            raise ValueError("Selected 1min input changed since plan freeze")
    if sum(Path(p).stat().st_size for p in paths) > MAX_INPUT_BYTES:
        raise ValueError(
            "Selected date exceeds input budget; revise unit before execution"
        )
    with connection(base, files=paths, budget=BUDGET) as c:
        c.execute(
            "CREATE TABLE missing AS SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=?",
            [str(base / "missing.parquet"), day],
        )
        c.execute(
            "CREATE TABLE parents AS SELECT DISTINCT latest_ts_code,one_code,trade_date FROM missing"
        )
        if c.execute(
            "SELECT count(*) FROM (SELECT latest_ts_code,trade_date FROM parents GROUP BY ALL HAVING count(*)>1)"
        ).fetchone()[0]:
            raise ValueError("A stock day must select only one 1min source")
        c.execute("CREATE TABLE payload AS " + raw_relation(paths))
        c.execute("""CREATE TABLE one_all AS SELECT p.*,r.latest_ts_code FROM payload p JOIN parents r
            ON p.ts_code=r.one_code AND p.trade_time::DATE=r.trade_date""")
        regular = """(strftime(trade_time,'%H:%M:%S') BETWEEN '09:30:00' AND '11:30:00'
            OR strftime(trade_time,'%H:%M:%S') BETWEEN '13:01:00' AND '15:00:00')"""
        c.execute(f"CREATE TABLE one AS SELECT * FROM one_all WHERE {regular}")
        invalid = c.execute(f"""SELECT count(*) FROM one WHERE freq<>1 OR freq IS NULL
            OR date_trunc('minute',trade_time)<>trade_time OR {core_bad()}
            OR amount IS NULL OR NOT isfinite(amount) OR amount<0 OR (vol=0 AND amount<>0)""").fetchone()[
            0
        ]
        complete = c.execute("""SELECT count(*) FROM (SELECT latest_ts_code,trade_time::DATE FROM one GROUP BY ALL
            HAVING count(*)=241 AND count(DISTINCT trade_time)=241)""").fetchone()[0]
        if (
            invalid
            or complete != c.execute("SELECT count(*) FROM parents").fetchone()[0]
        ):
            raise ValueError(
                "Selected stock day lacks a valid complete 241-point 1min input"
            )
        # Filter by missing keys before grouping; never compute unrequested target periods.
        c.execute("""CREATE TABLE calculated AS SELECT m.scope_id,m.latest_ts_code,m.one_code AS ts_code,
            m.freq::INTEGER AS freq,m.trade_time,arg_min(o.open,o.trade_time)::DOUBLE AS open,
            arg_max(o.close,o.trade_time)::DOUBLE AS close,max(o.high)::DOUBLE AS high,min(o.low)::DOUBLE AS low,
            sum(o.vol)::BIGINT AS vol,sum(o.amount)::DOUBLE AS amount,count(*) input_rows
            FROM missing m JOIN one o ON o.ts_code=m.one_code AND o.latest_ts_code=m.latest_ts_code
            AND ((strftime(m.trade_time,'%H:%M:%S')='09:30:00' AND o.trade_time=m.trade_time)
            OR (strftime(m.trade_time,'%H:%M:%S')<>'09:30:00' AND o.trade_time>m.trade_time-m.freq*INTERVAL '1 minute' AND o.trade_time<=m.trade_time))
            GROUP BY m.scope_id,m.latest_ts_code,m.one_code,m.freq,m.trade_time""")
        expected = c.execute("SELECT count(*) FROM missing").fetchone()[0]
        count, bad = c.execute("""SELECT count(*),count(*) FILTER(WHERE input_rows<>
            CASE WHEN strftime(trade_time,'%H:%M:%S')='09:30:00' THEN 1 ELSE freq END) FROM calculated""").fetchone()
        if count != expected or bad:
            raise ValueError("Calculated keys/windows differ from frozen missing keys")
        c.execute("""CREATE TABLE additions AS SELECT ts_code,freq,trade_time,open,close,high,low,vol,amount,
            CASE WHEN ends_with(ts_code,'.SH') THEN 'SSE' WHEN ends_with(ts_code,'.SZ') THEN 'SZSE'
            WHEN ends_with(ts_code,'.BJ') THEN 'BSE' ELSE NULL END::VARCHAR AS exchange,
            CASE WHEN vol>0 THEN amount/vol ELSE close END::DOUBLE AS vwap FROM calculated""")
        if c.execute(
            f"SELECT count(*) FROM additions WHERE {core_bad()} OR NOT isfinite(amount) OR NOT isfinite(vwap) OR exchange IS NULL"
        ).fetchone()[0]:
            raise ValueError("Invalid calculated values or identity")
        if c.execute(
            """SELECT count(*) FROM calculated a JOIN read_parquet(?,hive_partitioning=false) n USING(scope_id,trade_time)""",
            [str(base / "existing.parquet")],
        ).fetchone()[0]:
            raise ValueError("Calculated record would overwrite a source record")
        if cancelled():
            raise InterruptedError("Cancelled before date output")
        parquet(
            c,
            f"SELECT {','.join(COLUMNS)} FROM additions ORDER BY ts_code,freq,trade_time",
            destination / "rows.parquet",
        )
        parquet(
            c,
            f"""SELECT a.scope_id,a.latest_ts_code,a.ts_code,a.freq,a.trade_time,
            'aggregated' origin,1 source_freq,{literal(RULE)} AS rule,{literal(plan["hash"])} aggregation_plan_hash,
            m.one_paths input_paths FROM calculated a JOIN missing m USING(scope_id,trade_time)
            ORDER BY a.ts_code,a.freq,a.trade_time""",
            destination / "lineage.parquet",
        )
        equal = c.execute(
            """SELECT count(*) FROM ((SELECT * FROM additions EXCEPT ALL SELECT * FROM read_parquet(?,hive_partitioning=false))
            UNION ALL (SELECT * FROM read_parquet(?,hive_partitioning=false) EXCEPT ALL SELECT * FROM additions))""",
            [str(destination / "rows.parquet")] * 2,
        ).fetchone()[0]
        if equal:
            raise ValueError("Serialized candidate differs from calculation")
        if cancelled():
            raise InterruptedError(
                "Cancelled before completion; uncommitted date can be rebuilt"
            )
    state = {
        "plan_hash": plan["hash"],
        "day": day,
        "rows": expected,
        "artifacts": {
            name: file_digest(destination / name)
            for name in ["rows.parquet", "lineage.parquet"]
        },
    }
    atomic_json(state_path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freeze = commands.add_parser("plan")
    for name in ["manifest", "scope", "output", "recovery-hash"]:
        freeze.add_argument("--" + name, required=True)
    build = commands.add_parser("build")
    build.add_argument("--plan", required=True)
    build.add_argument("--date", action="append", required=True)
    args = parser.parse_args(argv)
    if args.action == "plan":
        recovery = RecoveryRun(
            Path(args.scope).parent / "plan.json", args.recovery_hash
        )
        recovery.require_operational_roots()
        if Path(args.scope).absolute() != recovery.plan_dir / "scope.parquet":
            raise ValueError("Use the original frozen recovery scope")
        result = freeze_missing_plan(
            args.manifest, args.scope, args.output, args.recovery_hash
        )
        print(json.dumps(result["counts"]), flush=True)
        return result
    if len(args.date) > 10 or len(set(args.date)) != len(args.date):
        raise ValueError("Select at most ten distinct dates explicitly")
    frozen = verify_plan(args.plan)
    for day in args.date:
        check_unit(5, day)
    with connection(Path(args.plan).parent, budget=BUDGET) as c:
        paths = c.execute(
            "SELECT DISTINCT unnest(one_paths) FROM read_parquet(?,hive_partitioning=false) WHERE trade_date IN (SELECT unnest(?::DATE[]))",
            [str(Path(args.plan).parent / "missing.parquet"), args.date],
        ).fetchall()
    if sum(frozen["inputs"][p]["size"] for (p,) in paths) > MAX_INPUT_BYTES:
        raise ValueError("Selected batch exceeds input byte budget")
    stop = False

    def cancel(*_):
        nonlocal stop
        stop = True

    handlers = {s: signal.signal(s, cancel) for s in [signal.SIGINT, signal.SIGTERM]}
    try:
        return [build_and_report(args.plan, day, lambda: stop) for day in args.date]
    finally:
        for s, h in handlers.items():
            signal.signal(s, h)


def build_and_report(plan, day, cancelled):
    try:
        result = build_date(plan, day, cancelled=cancelled)
    except (ValueError, InterruptedError) as exc:
        # Preserve evidence for a stopped unit; never mark an incomplete date complete.
        check_unit(5, day)
        atomic_json(
            stage_path(Path(plan).parent / "additions" / day / "last-stop.json"),
            {"day": day, "error_type": type(exc).__name__, "reason": str(exc)},
        )
        raise
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    main()
