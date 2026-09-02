"""CLI for the reviewed stock daily trend-channel history bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from orchestrator.defs.bootstrap.stock_daily_trend_channel_history import (
    BOOTSTRAP_MAX_SEGMENTS_PER_PROCESS,
    audit_stock_daily_trend_channel_history_candidates,
    final_audit_stock_daily_trend_channel_history,
    generate_stock_daily_trend_channel_history,
    load_stock_daily_trend_channel_history_plan,
    plan_stock_daily_trend_channel_history,
    promote_stock_daily_trend_channel_history,
    validate_stock_daily_trend_channel_history_private_stage,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan = plan_stock_daily_trend_channel_history(
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            output_dir=args.output_dir,
        )
        print(
            json.dumps(
                {
                    "report_path": str(plan.report_path),
                    "plan_id": plan.plan_id,
                    "plan_hash": plan.plan_hash,
                    "should_stop": plan.should_stop,
                    "stop_reasons": list(plan.stop_reasons),
                },
                ensure_ascii=False,
            )
        )
        return int(plan.should_stop)

    plan = load_stock_daily_trend_channel_history_plan(args.plan_report)
    if args.command in {"sample", "benchmark"}:
        report = validate_stock_daily_trend_channel_history_private_stage(
            plan=plan,
            expected_plan_id=args.plan_id,
            expected_plan_hash=args.plan_hash,
            stage=args.command,
            output_root=args.private_output_root,
            trade_day_count=args.trade_day_count,
            stock_codes=tuple(args.stock_code or ()),
            dry_run=not args.apply,
            confirm_write=args.apply,
        )
        _write_report(args.output, report)
        print(args.output)
        return int(not bool(report.get("audit_passed", True)))
    if args.command == "generate":
        report = generate_stock_daily_trend_channel_history(
            plan=plan,
            expected_plan_id=args.plan_id,
            expected_plan_hash=args.plan_hash,
            expected_start_date=args.start_date,
            expected_end_date=args.end_date,
            checkpoint_path=args.checkpoint,
            dry_run=not args.apply,
            confirm_write=args.apply,
            segment_count_limit=args.segment_count_limit,
        )
        _write_report(args.output, report)
        print(args.output)
        return 0
    if args.command == "audit-files":
        audit_stock_daily_trend_channel_history_candidates(
            plan=plan,
            expected_plan_id=args.plan_id,
            expected_plan_hash=args.plan_hash,
            expected_start_date=args.start_date,
            expected_end_date=args.end_date,
            checkpoint_path=args.checkpoint,
            output_path=args.output,
        )
        print(args.output)
        return 0
    if args.command == "promote":
        promote_stock_daily_trend_channel_history(
            plan=plan,
            expected_plan_id=args.plan_id,
            expected_plan_hash=args.plan_hash,
            expected_start_date=args.start_date,
            expected_end_date=args.end_date,
            audit_report_path=args.audit_report,
            expected_audit_hash=args.audit_hash,
            promotion_checkpoint_path=args.promotion_checkpoint,
            output_path=args.output,
            dry_run=not args.apply,
            confirm_write=args.apply,
        )
        print(args.output)
        return 0
    final_audit_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=args.plan_id,
        expected_plan_hash=args.plan_hash,
        expected_start_date=args.start_date,
        expected_end_date=args.end_date,
        promote_report_path=args.promote_report,
        expected_promote_hash=args.promote_hash,
        output_path=args.output,
    )
    print(args.output)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    plan.add_argument(
        "--staging-root",
        type=Path,
        default=Path(DEFAULT_LAKE_STAGING_ROOT),
    )
    plan.add_argument("--output-dir", type=Path, default=Path("/private/tmp"))

    for command in ("sample", "benchmark"):
        stage = subparsers.add_parser(command)
        _add_plan_identity_args(stage, include_range=False)
        stage.add_argument("--private-output-root", type=Path, required=True)
        stage.add_argument("--trade-day-count", type=int, required=True)
        stage.add_argument("--stock-code", action="append")
        stage.add_argument("--output", type=Path, required=True)
        stage.add_argument("--apply", action="store_true")

    generate = subparsers.add_parser("generate")
    _add_plan_identity_args(generate)
    generate.add_argument("--checkpoint", type=Path, required=True)
    generate.add_argument(
        "--segment-count-limit",
        type=int,
        default=1,
        choices=range(1, BOOTSTRAP_MAX_SEGMENTS_PER_PROCESS + 1),
    )
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--apply", action="store_true")

    audit = subparsers.add_parser("audit-files")
    _add_plan_identity_args(audit)
    audit.add_argument("--checkpoint", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)

    promote = subparsers.add_parser("promote")
    _add_plan_identity_args(promote)
    promote.add_argument("--audit-report", type=Path, required=True)
    promote.add_argument("--audit-hash", required=True)
    promote.add_argument("--promotion-checkpoint", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    promote.add_argument("--apply", action="store_true")

    final_audit = subparsers.add_parser("final-audit")
    _add_plan_identity_args(final_audit)
    final_audit.add_argument("--promote-report", type=Path, required=True)
    final_audit.add_argument("--promote-hash", required=True)
    final_audit.add_argument("--output", type=Path, required=True)
    return parser


def _add_plan_identity_args(
    parser: argparse.ArgumentParser,
    *,
    include_range: bool = True,
) -> None:
    parser.add_argument("--plan-report", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-hash", required=True)
    if include_range:
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)


def _write_report(path: Path, payload: dict[str, object]) -> None:
    normalized = Path(path).resolve()
    normalized.parent.mkdir(parents=True, exist_ok=True)
    pending = normalized.with_name(f".{normalized.name}.pending-{uuid.uuid4().hex}")
    pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, normalized)


if __name__ == "__main__":
    raise SystemExit(main())
