"""Direct-source period bootstrap. Default is read-only preparation; apply is explicit."""

from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stock_period_history import (
    load_scope,
    replay_events,
    roots,
    run_period,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_period import VERSION, StockPeriodPolicy


def _run_reporting(instance, operation, *, handoff=False):
    """One real run for all checks in an explicit CLI operation."""
    import dagster as dg

    @dg.op
    def report(context):
        return operation(context)

    @dg.job(name="stock_period_handoff" if handoff else "stock_period_event_report")
    def reporting():
        report()

    result = reporting.execute_in_process(instance=instance)
    return result.output_for_node("report")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "apply", "resume", "events", "handoff"),
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
    parser.add_argument(
        "--rss-limit-gib",
        type=int,
        help="Override process RSS for an existing bootstrap resume or bound handoff resume (positive GiB).",
    )
    args = parser.parse_args(argv)
    if args.rss_limit_gib is not None and (
        args.action not in ("resume", "handoff") or args.rss_limit_gib <= 0
    ):
        parser.error("--rss-limit-gib requires resume/handoff and a positive integer")
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
    if args.action in ("resume", "events", "handoff"):
        import re

        from orchestrator.defs.io.stock_period_raw import read_json
        from orchestrator.defs.run_contracts.stock_period import verify_execution

        if not args.run_id or not re.fullmatch(r"[0-9a-f]{64}", args.run_id):
            parser.error("resume/events/handoff require --run-id")
        frozen = read_json(
            staging / "stock_period" / "runs" / args.run_id / "manifest.json"
        )
        verify_execution(frozen, args.run_id)
        if frozen["identity"]["root"] != str(root):
            raise ValueError("period_resume_identity_changed")
        if (
            args.rss_limit_gib is not None
            and frozen["identity"]["intent"]["mode"] != "bootstrap"
        ):
            parser.error("--rss-limit-gib requires an existing bootstrap")
        if (
            args.rss_limit_gib is not None
            and args.action == "handoff"
            and "handoff" not in frozen
        ):
            parser.error("--rss-limit-gib requires an existing bound handoff")
        if args.action == "events" and frozen["phase"] not in (
            "files_complete",
            "events_complete",
        ):
            raise ValueError("period_event_files_incomplete")
        if args.action == "resume" and frozen["phase"] in (
            "files_complete",
            "events_complete",
        ):
            raise ValueError("period_delivery_events_required:use_existing_events_action")
        if frozen["phase"] == "deleting" and not args.confirm_delete_existing:
            parser.error("resume deletion requires --confirm-delete-existing")
    interrupted = False

    def cancel(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
    instance = None
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
        if args.action in ("events", "handoff"):
            import dagster as dg

            from orchestrator.defs.stock_period_update import (
                confirm_period_delivery,
                handoff_bootstrap,
                report_completion_events,
                report_file_events,
            )

            instance = dg.DagsterInstance.get()

        def confirm_delivery(run):
            return confirm_period_delivery(
                instance, run, root=root, staging=staging, cancel=lambda: interrupted
            )
        if args.action == "events":

            def operation(context):
                return replay_events(
                    staging / "stock_period/runs" / args.run_id,
                    root=root,
                    staging=staging,
                    events=lambda item, *, completion: report_file_events(
                        instance, item, completion=completion, context=context
                    ),
                    completion_events=lambda notice: report_completion_events(
                        instance, notice
                    ),
                    confirm_delivery=confirm_delivery,
                    cancel=lambda: interrupted,
                )

            if frozen["phase"] == "events_complete" and all(
                (
                    staging
                    / "stock_period/runs"
                    / args.run_id
                    / "events/completion"
                    / (f + ".json")
                ).exists()
                for f in {
                    i["freq"]
                    for i in read_json(
                        staging / "stock_period/runs" / args.run_id / "complete.json"
                    )["files"]
                }
            ):
                result = replay_events(
                    staging / "stock_period/runs" / args.run_id,
                    root=root,
                    staging=staging,
                    confirm_delivery=confirm_delivery,
                    cancel=lambda: interrupted,
                )
            else:
                result = _run_reporting(instance, operation)
        elif args.action == "handoff":

            def operation(context):
                return handoff_bootstrap(
                    root=root,
                    staging=staging,
                    run=staging / "stock_period/runs" / args.run_id,
                    runtime_rss_bytes=args.rss_limit_gib * 1024**3
                    if args.rss_limit_gib is not None
                    else None,
                    events=lambda item, *, completion: report_file_events(
                        instance, item, completion=completion, context=context
                    ),
                    completion_events=lambda notice: report_completion_events(
                        instance, notice
                    ),
                    confirm_delivery=confirm_delivery,
                    cancel=lambda: interrupted,
                    progress=lambda event: print(json.dumps(event), flush=True),
                )

            from orchestrator.defs.io.stock_period_raw import read_json

            baseline = read_json(staging / "stock_period/baseline.json")
            ready = (
                baseline.get("status") == "ready"
                and baseline.get("run_id") == args.run_id
            )
            state = (
                operation(None)
                if ready
                else _run_reporting(instance, operation, handoff=True)
            )
            result = {
                "run_id": args.run_id,
                "files": [],
                "events_complete": True,
                "handoff": state,
            }
        else:
            result = run_period(
                root=root,
                staging=staging,
                listed=listed,
                aliases=aliases,
                intent=intent,
                confirmed_retired=intent.get("retired_codes", ()),
                policy=StockPeriodPolicy(**frozen["identity"]["policy"])
                if frozen
                else StockPeriodPolicy(),
                runtime_rss_bytes=args.rss_limit_gib * 1024**3
                if args.rss_limit_gib is not None
                else None,
                cancel=lambda: interrupted,
                progress=lambda event: print(json.dumps(event), flush=True),
            )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "files": len(result["files"]),
                    "events_reported": result.get("events_complete", False),
                }
            )
        )
    finally:
        if instance is not None:
            instance.dispose()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
