"""CLI for reviewed major-index nine-turn runless event registration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.major_index_nineturn_events import (
    MAX_EVENT_PARTITIONS_PER_PROCESS,
    load_major_index_nineturn_event_plan,
    plan_major_index_nineturn_events,
    post_audit_major_index_nineturn_events,
    report_major_index_nineturn_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    instance = dg.DagsterInstance.get()
    if args.command == "plan":
        plan = plan_major_index_nineturn_events(
            instance=instance,
            history_plan_path=Path(args.history_plan),
            history_audit_path=Path(args.history_audit),
            lake_root=Path(args.lake_root),
            output_dir=Path(args.output_dir),
        )
        report = {
            "report_path": str(plan.report_path),
            "manifest_path": str(plan.manifest_path),
            "plan_fingerprint": plan.plan_fingerprint,
            "should_stop": plan.should_stop,
            "stop_reasons": list(plan.stop_reasons),
            "candidate_partition_count": plan.report["candidate_partition_count"],
            "planned_materialization_event_count": plan.report[
                "planned_materialization_event_count"
            ],
            "planned_check_event_count": plan.report[
                "planned_check_event_count"
            ],
            "planned_event_count": plan.report["planned_event_count"],
            "elapsed_ms": plan.report["elapsed_ms"],
        }
        print(json.dumps(report, ensure_ascii=False))
        return int(plan.should_stop)

    plan = load_major_index_nineturn_event_plan(Path(args.plan_report))
    if args.command == "apply":
        if not args.apply:
            parser.error("event apply requires explicit --apply")
        report = report_major_index_nineturn_events(
            instance=instance,
            plan=plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            checkpoint_path=Path(args.checkpoint_path),
            staging_root=Path(args.staging_root),
            lake_root=Path(args.lake_root),
            partition_limit=args.partition_limit,
            sample_identity=args.sample_identity,
        )
    else:
        report = post_audit_major_index_nineturn_events(
            instance=instance,
            plan=plan,
            checkpoint_path=Path(args.checkpoint_path),
            lake_root=Path(args.lake_root),
        )
    print(json.dumps(report, ensure_ascii=False))
    return int(bool(report.get("should_stop", False)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--history-plan", required=True)
    plan.add_argument("--history-audit", required=True)
    plan.add_argument("--output-dir", required=True)

    for name in ("apply", "post-audit"):
        command = subparsers.add_parser(name)
        command.add_argument("--plan-report", required=True)
        command.add_argument("--plan-fingerprint", required=True)
        command.add_argument("--checkpoint-path", required=True)
        if name == "apply":
            command.add_argument(
                "--partition-limit",
                type=int,
                default=1,
                choices=range(1, MAX_EVENT_PARTITIONS_PER_PROCESS + 1),
            )
            command.add_argument("--sample-identity")
            command.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
