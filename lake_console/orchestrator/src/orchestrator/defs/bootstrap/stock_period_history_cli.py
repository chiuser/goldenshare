"""Direct-source period bootstrap. Default is read-only preparation; apply is explicit."""

from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stock_period_history import (
    load_scope,
    roots,
    run_period,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_period import VERSION, StockPeriodPolicy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "apply", "resume", "events"),
        nargs="?",
        default="prepare",
    )
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT)
    )
    parser.add_argument("--request-id")
    parser.add_argument("--run-id")
    parser.add_argument("--confirm-delete-existing", action="store_true")
    args = parser.parse_args(argv)
    root, staging = roots(args.lake_root, args.staging_root)
    if args.action == "prepare":
        print(
            json.dumps(
                {
                    "mode": "bootstrap",
                    "roots": [
                        str(root / "raw/tushare/stk_period_bar_adj_week"),
                        str(root / "raw/tushare/stk_period_bar_adj_month"),
                    ],
                    "request_id": args.request_id,
                    "applied": False,
                }
            )
        )
        return 0
    if args.action == "apply" and (
        not args.confirm_delete_existing or not args.request_id
    ):
        parser.error("apply requires --request-id and --confirm-delete-existing")
    frozen = None
    if args.action in ("resume", "events"):
        import re

        from orchestrator.defs.io.stock_period_raw import read_json
        from orchestrator.defs.run_contracts.stock_period import verify_execution

        if not args.run_id or not re.fullmatch(r"[0-9a-f]{64}", args.run_id):
            parser.error("resume/events require --run-id")
        frozen = read_json(
            staging / "stock_period" / "runs" / args.run_id / "manifest.json"
        )
        verify_execution(frozen, args.run_id)
        if frozen["identity"]["root"] != str(root):
            raise ValueError("period_resume_identity_changed")
        if args.action == "events" and frozen["phase"] not in (
            "files_complete",
            "complete",
        ):
            raise ValueError("period_event_files_incomplete")
        if frozen["phase"] == "deleting" and not args.confirm_delete_existing:
            parser.error("resume deletion requires --confirm-delete-existing")
    interrupted = False

    def cancel(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        if frozen is None:
            listed, aliases = load_scope(root, staging / "stock_period" / "scope")
            intent = {
                "version": VERSION,
                "mode": "bootstrap",
                "frequencies": ["week", "month"],
                "codes": sorted(listed),
                "request_id": args.request_id,
            }
        else:
            listed = set(frozen["identity"]["listed"])
            aliases = frozen["identity"]["aliases"]
            intent = frozen["identity"]["intent"]
        instance = None
        if args.action == "events":
            import dagster as dg

            from orchestrator.defs.stock_period_update import report_file_events

            instance = dg.DagsterInstance.get()
        result = run_period(
            root=root,
            staging=staging,
            listed=listed,
            aliases=aliases,
            intent=intent,
            policy=StockPeriodPolicy(**frozen["identity"]["policy"])
            if frozen
            else StockPeriodPolicy(),
            events=(lambda item: report_file_events(instance, item))
            if instance is not None
            else None,
            cancel=lambda: interrupted,
            progress=lambda event: print(json.dumps(event), flush=True),
        )
        if args.action == "events" and intent["mode"] == "bootstrap":
            from datetime import date

            from orchestrator.defs.bootstrap.stock_period_history import writer
            from orchestrator.defs.io.stock_period_raw import atomic_json, read_json
            from orchestrator.defs.stock_period_update import (
                bootstrap_watermarks,
                calendar_days,
            )

            manifest = read_json(Path(result["path"]) / "manifest.json")
            coordinates = list(manifest.get("source_asof", {}).values())
            if len(coordinates) != 2 or not all(coordinates):
                raise ValueError("period_handoff_source_asof_missing")
            oldest = min(coordinates)
            asof = date(int(oldest[:4]), int(oldest[4:6]), int(oldest[6:]))
            statepath = staging / "stock_period" / "daily.json"
            with writer(staging):
                prior = read_json(statepath) if statepath.exists() else {}
                if prior.get("baseline_run_id") != result["run_id"]:
                    state = bootstrap_watermarks(
                        asof, calendar_days(root, staging / "stock_period" / "calendar")
                    )
                    state["baseline_run_id"] = result["run_id"]
                    atomic_json(statepath, state)
            instance.dispose()
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "files": len(result["files"]),
                    "events_reported": args.action == "events",
                }
            )
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
