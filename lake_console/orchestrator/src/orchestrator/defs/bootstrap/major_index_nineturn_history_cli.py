"""CLI for reviewed, bounded major-index nine-turn history generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrator.defs.bootstrap.major_index_nineturn_history import (
    MAX_BATCHES_PER_PROCESS,
    build_major_index_nineturn_history,
    load_major_index_nineturn_history_plan,
    plan_major_index_nineturn_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "plan":
        plan = plan_major_index_nineturn_history(
            lake_root=Path(args.lake_root),
            asset_keys=tuple(args.asset_keys) if args.asset_keys else None,
            output_dir=Path(args.output_dir),
        )
        print(
            json.dumps(
                {
                    "report_path": str(plan.report_path),
                    "plan_fingerprint": plan.plan_fingerprint,
                    "should_stop": plan.should_stop,
                    "stop_reasons": list(plan.stop_reasons),
                    "asset_count": plan.report["asset_count"],
                    "batch_count": plan.report["batch_count"],
                    "source_file_count": plan.report["source_file_count"],
                    "source_row_count": plan.report["source_row_count"],
                    "expected_target_file_count": plan.report[
                        "expected_target_file_count"
                    ],
                    "existing_target_file_count": plan.report[
                        "existing_target_file_count"
                    ],
                },
                ensure_ascii=False,
            )
        )
        return int(plan.should_stop)

    if not args.apply:
        parser.error("build requires explicit --apply after plan review")
    plan = load_major_index_nineturn_history_plan(Path(args.plan_report))
    report = build_major_index_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=args.plan_fingerprint,
        confirm_write=True,
        staging_root=Path(args.staging_root),
        checkpoint_path=Path(args.checkpoint_path),
        batch_count_limit=args.batch_count_limit,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="write a read-only frozen plan")
    plan.add_argument("--asset-keys", nargs="*")
    plan.add_argument("--output-dir", default="/private/tmp")

    build = subparsers.add_parser(
        "build",
        help="apply at most ten reviewed 20-day batches and checkpoint progress",
    )
    build.add_argument("--plan-report", required=True)
    build.add_argument("--plan-fingerprint", required=True)
    build.add_argument("--checkpoint-path", required=True)
    build.add_argument(
        "--batch-count-limit",
        type=int,
        default=1,
        choices=range(1, MAX_BATCHES_PER_PROCESS + 1),
    )
    build.add_argument("--apply", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
