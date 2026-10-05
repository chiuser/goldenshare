"""Monthly runless bootstrap events: read-only default, explicit bounded APPLY."""

import argparse
import signal
import tempfile
from pathlib import Path

from orchestrator.defs.bootstrap.stock_monthly_events import (
    MonthlyEventPolicy,
    apply_monthly_events,
    audit_monthly_event_files,
    audit_monthly_readiness_samples,
    freeze_monthly_event_plan,
    verify_monthly_event_plan,
)
from orchestrator.defs.bootstrap.stock_monthly_files import (
    monthly_file_hash,
    monthly_file_lock,
    read_monthly_json,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_weekly_event_instance import (
    open_weekly_event_instance,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("dry-run", "register", "apply", "audit"), default="dry-run"
    )
    parser.add_argument("--history-plan", type=Path, action="append")
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT)
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--months", nargs="+")
    args = parser.parse_args(argv)
    policy = MonthlyEventPolicy()
    allowed_outputs = (
        Path(__file__).resolve().parents[6] / "reports",
        Path("/private/tmp"),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not all(
        any(p.absolute().is_relative_to(root) for root in allowed_outputs)
        for p in (args.plan, args.report)
    ):
        parser.error(
            "event outputs must be repository reports or private temporary files"
        )
    inputs = [args.plan, *(args.history_plan or [])]
    if args.report.absolute() in {p.absolute() for p in inputs}:
        parser.error("report must not overwrite frozen input")
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    if args.mode == "dry-run":
        if (
            args.apply
            or args.plan.exists()
            or len(args.history_plan or []) != 2
            or args.months
        ):
            parser.error(
                "dry-run requires two history plans and a new event plan, without --apply"
            )
        evidence = {
            "lake_root": str(args.lake_root),
            "staging_root": str(args.staging_root),
            "history_plans": [
                {
                    "path": str(p.absolute()),
                    "sha256": monthly_file_hash(
                        p.absolute(), max_bytes=policy.plan_max_bytes
                    ),
                }
                for p in args.history_plan
            ],
        }
        entries, metrics = audit_monthly_event_files(evidence, cancel=lambda: cancelled)
        with open_weekly_event_instance() as (instance, identity):
            plan = freeze_monthly_event_plan(
                instance, entries, instance_identity=identity, evidence=evidence
            )
        write_monthly_json(args.plan.absolute(), plan, policy.plan_max_bytes)
        result = {
            "status": "dry_run",
            "plan_hash": plan["plan_hash"],
            "counts": plan["counts"],
            "missing_registrations": len(plan["missing_registrations"]),
            "physical_audits": metrics,
        }
    else:
        if args.history_plan or (args.mode == "audit" and args.apply):
            parser.error("apply/audit uses frozen event plan only; audit is read-only")
        plan = read_monthly_json(args.plan.absolute(), policy.plan_max_bytes)
        verify_monthly_event_plan(plan)
        if args.lake_root != Path(
            plan["evidence"]["lake_root"]
        ) or args.staging_root != Path(plan["evidence"]["staging_root"]):
            parser.error("roots must match frozen plan")
        if args.mode == "audit":
            entries, metrics = audit_monthly_event_files(
                plan["evidence"], cancel=lambda: cancelled
            )
            if [{k: e[k] for k in entries[0]} for e in plan["entries"]] != entries:
                raise ValueError("monthly_event_physical_evidence_changed")
            with open_weekly_event_instance(identity=plan["instance_identity"]) as (
                instance,
                _,
            ):
                current = freeze_monthly_event_plan(
                    instance,
                    entries,
                    instance_identity=plan["instance_identity"],
                    evidence=plan["evidence"],
                )
                samples = audit_monthly_readiness_samples(
                    instance, entries, args.lake_root
                )
            result = {
                "status": "audit",
                "plan_hash": plan["plan_hash"],
                "counts": current["counts"],
                "missing_registrations": len(current["missing_registrations"]),
                "physical_audits": metrics,
                "readiness_samples": samples,
            }
            if (
                current["counts"]["materializations"]
                or current["counts"]["checks"]
                or current["missing_registrations"]
                or not all(s["ready"] for s in samples)
            ):
                result["status"] = "incomplete"
        else:
            if not args.apply:
                parser.error("writes require explicit --apply")
            if (
                not args.plan_sha256
                or monthly_file_hash(
                    args.plan.absolute(), max_bytes=policy.plan_max_bytes
                )
                != args.plan_sha256
            ):
                parser.error("writes require frozen plan file SHA256")
            with (
                monthly_file_lock(
                    args.staging_root / "stock_monthly_event_writer.lock"
                ),
                open_weekly_event_instance(identity=plan["instance_identity"]) as (
                    instance,
                    _,
                ),
            ):
                result = apply_monthly_events(
                    instance,
                    plan,
                    checkpoint=args.report.absolute(),
                    start=args.start,
                    count=args.count,
                    months=args.months,
                    register=args.mode == "register",
                    cancel=lambda: cancelled,
                )
            result.update(
                status="applied",
                plan_hash=plan["plan_hash"],
                mode=args.mode,
                start=args.start,
                count=args.count,
                months=args.months,
            )
    write_monthly_json(args.report.absolute(), result, policy.plan_max_bytes)
    return 0 if result.get("status") != "incomplete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
