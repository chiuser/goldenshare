"""Controlled recent-window events for recovered BSE recursive minute assets."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_bse_recursive_events import (
    apply_bse_recursive_event_refresh,
    load_recursive_event_refresh_plan_inputs,
    plan_bse_recursive_event_refresh,
    post_audit_bse_recursive_event_refresh,
    write_recursive_event_refresh_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    with dg.DagsterInstance.get() as instance:
        if args.command == "plan":
            plan = plan_bse_recursive_event_refresh(
                instance=instance,
                manifest_paths=tuple(args.manifest),
                lake_root=args.lake_root,
            )
            write_recursive_event_refresh_report(plan, args.output)
            print(args.output)
            return int(plan.should_stop)

        manifest_paths, reviewed_hash = load_recursive_event_refresh_plan_inputs(
            args.plan_report
        )
        plan = plan_bse_recursive_event_refresh(
            instance=instance,
            manifest_paths=manifest_paths,
            lake_root=args.lake_root,
        )
        if reviewed_hash != args.expected_plan_hash:
            parser.error("--expected-plan-hash does not match the reviewed report")
        if args.command == "apply":
            report = apply_bse_recursive_event_refresh(
                instance=instance,
                reviewed_plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                checkpoint_path=args.checkpoint,
            )
        else:
            if plan.plan_hash != args.expected_plan_hash:
                parser.error("current plan does not match --expected-plan-hash")
            report = post_audit_bse_recursive_event_refresh(
                instance=instance,
                plan=plan,
            )
        write_recursive_event_refresh_report(report, args.output)
        print(args.output)
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply", "post-audit"))
    parser.add_argument(
        "--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT)
    )
    parser.add_argument("--manifest", type=Path, action="append")
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--confirm-event-write", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command == "plan":
        if not args.manifest:
            parser.error("plan requires at least one --manifest")
        if (
            args.plan_report
            or args.expected_plan_hash
            or args.checkpoint
            or args.confirm_event_write
        ):
            parser.error("plan does not accept apply/post-audit arguments")
        return
    if args.manifest:
        parser.error(f"{args.command} reads manifests from --plan-report")
    if not args.plan_report or not args.expected_plan_hash:
        parser.error(
            f"{args.command} requires --plan-report and --expected-plan-hash"
        )
    if args.command == "apply":
        if not args.checkpoint or not args.confirm_event_write:
            parser.error(
                "apply requires --checkpoint and --confirm-event-write"
            )
    elif args.checkpoint or args.confirm_event_write:
        parser.error("post-audit does not accept apply arguments")


if __name__ == "__main__":
    raise SystemExit(main())
