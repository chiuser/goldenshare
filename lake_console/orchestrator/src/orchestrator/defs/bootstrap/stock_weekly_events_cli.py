"""Explicit weekly event dry-run / approved, bounded stage application."""

import argparse
import json
import signal
from pathlib import Path

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    _atomic_json,
)
from orchestrator.defs.bootstrap.stock_weekly_event_files import (
    audit_weekly_event_files,
)
from orchestrator.defs.bootstrap.stock_weekly_event_instance import (
    open_weekly_event_instance,
)
from orchestrator.defs.bootstrap.stock_weekly_events import (
    apply_weekly_events,
    audit_weekly_readiness_samples,
    freeze_weekly_event_plan,
    verify_weekly_event_plan,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dry-run", "register", "materializations", "checks", "audit"),
        default="dry-run",
    )
    parser.add_argument("--audits", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args(argv)
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    try:
        if args.mode == "dry-run":
            if args.apply or args.audits is None or args.plan.exists():
                parser.error(
                    "dry-run requires --audits and a new --plan; --apply forbidden"
                )
            if args.audits.stat().st_size > 1024 * 1024:
                raise WeeklyCaptureError("event_input_budget_exceeded")
            references = json.loads(args.audits.read_text())
            metrics = {}
            entries = audit_weekly_event_files(references, metrics=metrics)
            with open_weekly_event_instance() as (instance, identity):
                plan = freeze_weekly_event_plan(
                    instance, entries, instance_identity=identity
                )
            _atomic_json(args.plan, plan)
            _atomic_json(
                args.report,
                {
                    "status": "dry_run",
                    "plan_hash": plan["plan_hash"],
                    "counts": plan["counts"],
                    "registrations": len(plan["missing_registrations"]),
                    "physical_audit_metrics": metrics,
                },
            )
        else:
            if args.audits is not None or args.plan.stat().st_size > 8 * 1024 * 1024:
                parser.error("apply/audit requires the frozen plan, without --audits")
            plan = json.loads(args.plan.read_text())
            verify_weekly_event_plan(plan)
            if args.mode == "audit":
                if args.apply:
                    parser.error("audit is read-only")
                references = {
                    e["audit_path"]: e["audit_sha256"] for e in plan["entries"]
                }
                entries = audit_weekly_event_files(
                    [
                        {"path": path, "sha256": digest}
                        for path, digest in references.items()
                    ]
                )
                with open_weekly_event_instance(identity=plan["instance_identity"]) as (
                    instance,
                    _,
                ):
                    current = freeze_weekly_event_plan(
                        instance, entries, instance_identity=plan["instance_identity"]
                    )
                    samples = audit_weekly_readiness_samples(instance, entries)
                _atomic_json(
                    args.report,
                    {
                        "status": "audit",
                        "plan_hash": plan["plan_hash"],
                        "counts": current["counts"],
                        "registrations": len(current["missing_registrations"]),
                        "readiness_samples": samples,
                    },
                )
            else:
                if not args.apply:
                    parser.error("writes require explicit --apply")
                with open_weekly_event_instance(identity=plan["instance_identity"]) as (
                    instance,
                    _,
                ):
                    result = apply_weekly_events(
                        instance,
                        plan,
                        stage=args.mode,
                        checkpoint=args.report,
                        cancel=lambda: cancelled,
                        start=args.start,
                        count=args.count,
                    )
                print(json.dumps(result, sort_keys=True))
        return 0
    except WeeklyCaptureError as error:
        print(json.dumps({"status": "rejected", "reason_code": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
