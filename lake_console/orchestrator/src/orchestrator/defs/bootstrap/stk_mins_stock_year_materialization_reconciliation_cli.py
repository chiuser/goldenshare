"""CLI for trusted historical stock-year materialization recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_stock_year_materialization_reconciliation import (
    apply_stock_year_materialization_plan,
    audit_stock_year_materialization_plan,
    build_stock_year_materialization_plan,
    load_stock_year_materialization_plan,
    write_stock_year_materialization_report,
)


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("plan", "apply", "audit"))
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--backup-manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    instance = dg.DagsterInstance.get()

    if args.stage == "plan":
        if args.apply or args.plan_report is not None or args.backup_manifest is not None:
            parser.error("plan accepts only --output-dir")
        plan = build_stock_year_materialization_plan(instance=instance, output_dir=args.output_dir)
        print(plan.report_path)
        return plan.report_path

    if args.plan_report is None:
        parser.error("apply/audit require --plan-report")
    plan = load_stock_year_materialization_plan(args.plan_report)
    if args.stage == "apply":
        if not args.apply or args.backup_manifest is None:
            parser.error("apply requires --apply and --backup-manifest")
        report = apply_stock_year_materialization_plan(
            instance=instance,
            plan=plan,
            backup_manifest_path=args.backup_manifest,
            output_dir=args.output_dir,
        )
        output_path = write_stock_year_materialization_report(
            args.output_dir,
            "apply",
            report.to_dict(),
        )
    else:
        if args.apply or args.backup_manifest is not None:
            parser.error("audit is read-only and accepts no --apply or --backup-manifest")
        output_path = write_stock_year_materialization_report(
            args.output_dir,
            "audit",
            audit_stock_year_materialization_plan(instance=instance, plan=plan),
        )
    print(output_path)
    return output_path


if __name__ == "__main__":
    main()
