"""Read-only planning, explicit DG publication, and independent readback."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic

import duckdb

from orchestrator.defs.bootstrap import index_daily_volume_repair as repair
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    plan = actions.add_parser("plan")
    plan.add_argument("--source", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    for action in ("apply", "audit"):
        command = actions.add_parser(action)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--expected-plan-sha256", required=True)
        command.add_argument("--pilot", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    lake_root = Path(DEFAULT_LAKE_ROOT)
    started = monotonic()
    with duckdb.connect() as connection:
        approved = repair.approved_dates(connection, lake_root)
        if args.action == "plan":
            plan = repair.build_plan(
                connection, lake_root, args.source.read_bytes(), approved
            )
            payload = json.dumps(plan, sort_keys=True, allow_nan=False).encode()
            with args.output.open("xb") as stream:
                stream.write(payload)
            print(
                json.dumps(
                    {
                        "days": len(plan["days"]),
                        "files": len(plan["days"]) * len(repair.LAYERS),
                        "source_sha256": plan["source_sha256"],
                        "plan_sha256": hashlib.sha256(payload).hexdigest(),
                        "plan": str(args.output),
                        "elapsed_seconds": round(monotonic() - started, 2),
                    }
                ),
                flush=True,
            )
            return 0

        payload = args.plan.read_bytes()
        plan_hash = hashlib.sha256(payload).hexdigest()
        if plan_hash != args.expected_plan_sha256:
            raise ValueError("Frozen plan digest differs")
        plan = json.loads(payload)
        if plan["index"] != repair.CODE or tuple(plan["days"]) != approved[:-1]:
            raise ValueError("Frozen plan scope is outside the approved range")
        run_dir = (
            Path(DEFAULT_LAKE_STAGING_ROOT)
            / "index_daily_volume_repair"
            / f"plan={plan_hash}"
        )
        repair.audit_control(connection, lake_root, plan)
        dates = repair.PILOT_DATES if args.pilot else approved[:-1]
        if args.action == "apply" and not args.pilot:
            for day in repair.PILOT_DATES:
                repair.audit_day(connection, lake_root, run_dir, day, plan["days"][day])
        samples = {}
        for count, day in enumerate(dates, 1):
            entry = plan["days"][day]
            if args.action == "apply":
                results = repair.apply_day(
                    connection, lake_root, run_dir, plan_hash, day, entry
                )
            else:
                results = repair.audit_day(connection, lake_root, run_dir, day, entry)
            if day in repair.PILOT_DATES:
                samples[day] = {
                    name: {field: facts[field] for field in ("vol", "amount")}
                    for name, facts in results.items()
                }
            if count == len(dates) or day[:7] != dates[count][:7]:
                print(f"{args.action} {day} {count}/{len(dates)}", flush=True)
        repair.audit_control(connection, lake_root, plan)
        print(
            json.dumps(
                {
                    "action": args.action,
                    "days": len(dates),
                    "files": len(dates) * len(repair.LAYERS),
                    "control_unchanged": repair.CONTROL,
                    "samples": samples,
                    "run_dir": str(run_dir),
                    "elapsed_seconds": round(monotonic() - started, 2),
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
