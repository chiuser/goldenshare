"""CLI for the non-active QFQ as-of-factor basis bootstrap."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_qfq_as_of_basis import (
    apply_stk_mins_qfq_as_of_basis_bootstrap,
    plan_stk_mins_qfq_as_of_basis_bootstrap,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan or explicitly apply the QFQ as-of-factor basis bootstrap."
    )
    parser.add_argument("stage", choices=("plan", "apply"))
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--partition-key", action="append", default=[])
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--plan-report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    if args.stage == "plan" and (args.apply or args.plan_report is not None):
        parser.error("plan is read-only and does not accept --apply or --plan-report.")
    if args.stage == "apply" and not args.apply:
        parser.error("apply requires explicit --apply.")
    if args.stage == "apply" and args.plan_report is None:
        parser.error("apply requires --plan-report from a reviewed plan.")

    selection = {
        "lake_root": args.lake_root,
        "partition_keys": tuple(args.partition_key) or None,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }
    if args.stage == "plan":
        report = plan_stk_mins_qfq_as_of_basis_bootstrap(**selection).to_report()
    else:
        expected_fingerprint = _plan_fingerprint_from_report(args.plan_report)
        report = apply_stk_mins_qfq_as_of_basis_bootstrap(
            **selection,
            expected_plan_fingerprint=expected_fingerprint,
        ).to_report()

    report_path = args.report_path or _default_report_path(args.stage)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(report_path)


def _plan_fingerprint_from_report(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"plan report does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"plan report is not valid JSON: {path}") from error
    fingerprint = payload.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError(f"plan report does not contain plan_fingerprint: {path}")
    return fingerprint


def _default_report_path(stage: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return Path(f"/private/tmp/stk_mins_qfq_as_of_basis_{stage}_{timestamp}.json")


if __name__ == "__main__":
    main()
