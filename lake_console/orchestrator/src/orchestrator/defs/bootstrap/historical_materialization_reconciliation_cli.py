"""CLI for offline historical Dagster materialization reconciliation."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.historical_materialization_reconciliation import (
    FAMILY_ASSET_KEYS,
    apply_historical_materialization_reconciliation,
    audit_historical_materialization_reconciliation,
    build_historical_materialization_reconciliation_plan,
    load_historical_materialization_reconciliation_plan,
    write_reconciliation_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("plan", "apply", "audit"))
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--families", nargs="+", choices=tuple(FAMILY_ASSET_KEYS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.stage == "plan":
        if args.apply or args.plan_report is not None or args.families is not None:
            parser.error("plan accepts only --lake-root and --output-dir")
        plan = build_historical_materialization_reconciliation_plan(
            instance=dg.DagsterInstance.get(),
            lake_root=args.lake_root,
            output_dir=args.output_dir,
        )
        print(plan.report_path)
        return plan.report_path

    if args.plan_report is None or not args.families:
        parser.error("apply/audit require --plan-report and --families")
    plan = load_historical_materialization_reconciliation_plan(args.plan_report)
    instance = dg.DagsterInstance.get()
    if args.stage == "apply":
        if not args.apply:
            parser.error("apply requires explicit --apply")
        report = apply_historical_materialization_reconciliation(
            instance=instance,
            plan=plan,
            lake_root=args.lake_root,
            families=args.families,
            dry_run=False,
            output_dir=args.output_dir,
        )
        output_path = write_reconciliation_report(args.output_dir, "apply", report.to_dict())
    else:
        if args.apply:
            parser.error("audit is read-only and does not accept --apply")
        output_path = write_reconciliation_report(
            args.output_dir,
            "audit",
            audit_historical_materialization_reconciliation(
                instance=instance,
                plan=plan,
                families=args.families,
            ),
        )
    print(output_path)
    return output_path


if __name__ == "__main__":
    main()
