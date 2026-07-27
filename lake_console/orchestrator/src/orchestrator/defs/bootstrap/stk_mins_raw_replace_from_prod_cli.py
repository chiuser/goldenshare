"""CLI for the non-active stock-minute raw recovery tool."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence

from orchestrator.defs.bootstrap.stk_mins_raw_replace_from_prod import (
    apply_stk_mins_raw_replace_from_prod,
    load_stk_mins_raw_replace_from_prod_plan,
    plan_stk_mins_raw_replace_from_prod,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def main(argv: Sequence[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or explicitly apply one five-frequency stk_mins raw replacement. "
            "This CLI is not an active Dagster definition."
        )
    )
    parser.add_argument("stage", choices=("plan", "apply"))
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.stage == "plan":
        if args.apply or args.plan_report is not None:
            parser.error("plan accepts no --apply or --plan-report")
        report = plan_stk_mins_raw_replace_from_prod(
            lake_root=args.lake_root,
            duckdb=DuckDBResource(),
            prod_postgres=ProdPostgresResource(),
            trade_date=args.trade_date,
        ).to_dict()
        output = args.output or _default_output("plan")
    else:
        if not args.apply or args.plan_report is None:
            parser.error("apply requires both --apply and --plan-report")
        plan = load_stk_mins_raw_replace_from_prod_plan(args.plan_report)
        if plan.trade_date != args.trade_date:
            parser.error("--trade-date must equal the reviewed plan trade_date")
        report = apply_stk_mins_raw_replace_from_prod(
            lake_root=args.lake_root,
            duckdb=DuckDBResource(),
            prod_postgres=ProdPostgresResource(),
            plan=plan,
            expected_plan_fingerprint=plan.plan_fingerprint,
            confirm_apply=True,
        ).to_dict()
        output = args.output or _default_output("apply")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return output


def _default_output(stage: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/private/tmp") / f"stk_mins_raw_replace_from_prod_{stage}_{timestamp}.json"


if __name__ == "__main__":
    main()
