"""Explicit phase CLI; never creates a Dagster instance or invokes downstreams."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_gap_recovery import (
    RecoveryRun,
    freeze_plan,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_fetch import load_source_batch
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import (
    build_candidate,
    compact_changed_raw,
    promote_candidate,
    selected_files,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_source import (
    SourceCache,
    compact_source_index,
)
from orchestrator.defs.resources import TushareResource


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    freeze = sub.add_parser("freeze")
    for name in ("draft", "audit", "output", "run-root"):
        freeze.add_argument("--" + name, required=True, type=Path)
    freeze.add_argument("--seed-input", action="append", type=Path, default=[])
    for action in ("status", "import-cache", "fetch", "build-raw", "promote-raw"):
        action_parser = sub.add_parser(action)
        action_parser.add_argument("--plan", required=True, type=Path)
        action_parser.add_argument("--plan-hash", required=True)
        if action != "status":
            action_parser.add_argument("--apply", action="store_true", required=True)
        if action == "fetch":
            action_parser.add_argument("--limit", required=True, type=int)
            action_parser.add_argument("--window-id", action="append", default=[])
        if action in ("build-raw", "promote-raw"):
            action_parser.add_argument(
                "--freq", required=True, type=int, choices=(1, 5, 15, 30, 60)
            )
            action_parser.add_argument("--limit", required=True, type=int)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.action == "freeze":
        from orchestrator.defs.bootstrap.stk_mins_gap_recovery import bounded_path
        from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT

        bounded_path(args.run_root, Path(DEFAULT_LAKE_STAGING_ROOT))
        plan = freeze_plan(
            draft=args.draft,
            audit=args.audit,
            output=args.output,
            run_root=args.run_root,
            seed_inputs=args.seed_input,
        )
        print(json.dumps(plan, ensure_ascii=False, default=str))
        return plan
    run = RecoveryRun(args.plan, args.plan_hash)
    run.require_operational_roots()
    if args.action == "status":
        states = {kind: {} for kind in ("windows", "files")}
        for kind, counts in states.items():
            for path in (run.root / kind).glob("*.json"):
                state = json.loads(path.read_text())
                if state["plan_hash"] != run.hash:
                    raise ValueError("Mixed plan checkpoints")
                status = state["status"]
                counts[status] = counts.get(status, 0) + 1
        print(
            json.dumps(
                {"plan_hash": run.hash, "states": states, "downstream": "not_executed"}
            )
        )
        return states
    if args.action == "fetch" and not 1 <= args.limit <= run.budget["source_batch"]:
        raise ValueError("Source batch exceeds frozen budget")
    if (
        args.action in ("build-raw", "promote-raw")
        and not 1 <= args.limit <= run.budget["file_batch"]
    ):
        raise ValueError("File batch exceeds frozen budget")
    token = (
        os.environ.get("TUSHARE_TOKEN", "").strip() if args.action == "fetch" else ""
    )
    if args.action == "fetch" and not token:
        raise ValueError(
            "TUSHARE_TOKEN must be supplied by the existing execution environment before fetch"
        )
    stop = False

    def cancel(signum, frame):
        nonlocal stop
        stop = True

    old_handlers = {
        s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        run.initialize()
        if args.action in ("import-cache", "fetch"):
            provider = TushareResource(token=token) if args.action == "fetch" else None
            cache = SourceCache(
                run,
                provider,
                cancelled=lambda: stop,
                progress=lambda event: print(json.dumps(event), flush=True),
            )
            cache.import_seeds()
            if args.action == "fetch":
                batch = load_source_batch(run, args.limit, args.window_id)
                cache.resolve_batch(batch)
            compact_source_index(run)
        else:
            files = selected_files(
                run,
                args.freq,
                args.limit,
                require_candidate=args.action == "promote-raw",
            )
            candidate_bytes = 0
            print(json.dumps({"eligible_files_in_batch": len(files)}), flush=True)
            for index, file in enumerate(files):
                if stop:
                    raise InterruptedError("Cancelled; no new file acquired")
                print(
                    json.dumps(
                        {
                            "stage": args.action,
                            "freq": args.freq,
                            "date": str(file["trade_date"]),
                            "completed": index,
                            "total": len(files),
                        }
                    ),
                    flush=True,
                )
                if args.action == "build-raw":
                    built = build_candidate(run, file, cancelled=lambda: stop)
                    candidate_bytes += built["candidate_fingerprint"]["size"]
                    if candidate_bytes > run.budget["candidate_bytes"]:
                        raise RuntimeError(
                            "Batch candidate byte budget exceeded; candidates retained"
                        )
                else:
                    promote_candidate(run, file, cancelled=lambda: stop)
            compact_changed_raw(run)
        print(
            json.dumps(
                {
                    "stage": args.action,
                    "status": "batch_finished",
                    "plan_hash": run.hash,
                }
            ),
            flush=True,
        )
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
