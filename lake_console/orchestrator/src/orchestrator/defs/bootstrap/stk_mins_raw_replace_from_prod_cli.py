"""CLI for the non-active stock-minute raw recovery tool."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_raw_replace_from_prod import (
    StkMinsRawReplaceFromProdError,
    _recovery_paths,
    _safe_child,
    _write_json,
    apply_stk_mins_raw_replace_from_prod,
    load_stk_mins_raw_replace_from_prod_plan,
    plan_stk_mins_raw_replace_from_prod,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def _report_output(output: Path | None, run_root: Path, stage: str) -> Path:
    default = run_root / ("plan.json" if stage == "plan" else "final-report.json")
    if output is None:
        return default
    output = _safe_child(output, run_root)
    if output == default:
        return output
    if (
        output.parent != run_root or output.suffix != ".json"
        or output.name in {"plan.json", "checkpoint.json", "final-report.json"}
        or output.name.startswith(".")
    ):
        raise StkMinsRawReplaceFromProdError("Output must be a non-reserved run-root JSON report", "scope_invalid")
    return output


def main(argv: Sequence[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or explicitly apply one five-frequency stk_mins raw replacement. "
            "Non-active CLI: apply requires a human maintenance window with other writers stopped."
        )
    )
    parser.add_argument("stage", choices=("plan", "apply"))
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT))
    parser.add_argument("--recovery-run-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--abort-before-promote", action="store_true")
    args = parser.parse_args(argv)

    if args.stage == "plan":
        if args.apply or args.plan_report is not None or args.abort_before_promote:
            parser.error("plan accepts no --apply, --plan-report or --abort-before-promote")
        run_id = args.recovery_run_id or str(uuid.uuid4())
        _, _, run_root = _recovery_paths(
            args.lake_root, args.staging_root, args.trade_date, run_id,
        )
        output = _report_output(args.output, run_root, args.stage)
        report = plan_stk_mins_raw_replace_from_prod(
            lake_root=args.lake_root, staging_root=args.staging_root, recovery_run_id=run_id,
            duckdb=DuckDBResource(), prod_postgres=ProdPostgresResource(), trade_date=args.trade_date,
        ).to_dict()
    else:
        if not args.apply or args.plan_report is None:
            parser.error("apply requires both --apply and --plan-report")
        plan = load_stk_mins_raw_replace_from_prod_plan(args.plan_report)
        if plan.trade_date != args.trade_date:
            parser.error("--trade-date must equal the reviewed plan trade_date")
        if args.recovery_run_id is not None and args.recovery_run_id != plan.recovery_run_id:
            parser.error("--recovery-run-id must equal the reviewed plan run id")
        _, _, run_root = _recovery_paths(
            args.lake_root, args.staging_root, args.trade_date, plan.recovery_run_id,
        )
        _safe_child(args.plan_report, run_root)
        output = _report_output(args.output, run_root, args.stage)
        report = apply_stk_mins_raw_replace_from_prod(
            lake_root=args.lake_root, staging_root=args.staging_root,
            duckdb=DuckDBResource(), prod_postgres=ProdPostgresResource(),
            plan=plan, expected_plan_fingerprint=plan.plan_fingerprint, confirm_apply=True,
            recovery_run_id=plan.recovery_run_id, abort_before_promote=args.abort_before_promote,
        ).to_dict()

    default = run_root / ("plan.json" if args.stage == "plan" else "final-report.json")
    if output != default:
        _write_json(output, report)
    print(output)
    if report.get("should_stop"):
        raise StkMinsRawReplaceFromProdError("Plan stopped; review stop_reasons", "scope_invalid")
    return output


if __name__ == "__main__":
    try:
        main()
    except (StkMinsRawReplaceFromProdError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
