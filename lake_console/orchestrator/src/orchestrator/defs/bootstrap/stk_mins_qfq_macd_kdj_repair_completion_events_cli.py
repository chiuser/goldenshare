from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

import dagster as dg

from orchestrator.defs.bootstrap.stk_mins_qfq_macd_kdj_repair_completion_events import (
    DEFAULT_HISTORY_PAGE_LIMIT,
    MAX_HISTORY_RECORDS_PER_CHECK_KEY,
    plan_stk_mins_qfq_macd_kdj_repair_completion_events,
    report_stk_mins_qfq_macd_kdj_repair_completion_events,
)


def main(argv: Sequence[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description="MACD/KDJ repair completion identity rehydration."
    )
    parser.add_argument("stage", choices=("plan-events", "report-events"))
    parser.add_argument(
        "--trade-date",
        action="append",
        required=True,
        dest="trade_dates",
        help="QFQ factor repair trigger date, repeat once per batch.",
    )
    parser.add_argument("--history-page-limit", type=int, default=DEFAULT_HISTORY_PAGE_LIMIT)
    parser.add_argument(
        "--max-history-records-per-check-key",
        type=int,
        default=MAX_HISTORY_RECORDS_PER_CHECK_KEY,
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--plan-report",
        type=Path,
        help="Required for --apply; must be the JSON emitted by plan-events.",
    )
    parser.add_argument("--report-dir", default="/private/tmp")
    args = parser.parse_args(argv)

    instance = dg.DagsterInstance.get()
    if args.stage == "plan-events":
        if args.apply or args.plan_report is not None:
            parser.error("plan-events is read-only and does not accept --apply or --plan-report.")
        payload = plan_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=args.trade_dates,
            history_page_limit=args.history_page_limit,
            max_history_records_per_check_key=args.max_history_records_per_check_key,
        ).to_dict()
    else:
        expected_plan_fingerprint = None
        if args.apply:
            if args.plan_report is None:
                parser.error("report-events --apply requires --plan-report.")
            expected_plan_fingerprint = _plan_fingerprint_from_report(args.plan_report)
        elif args.plan_report is not None:
            parser.error("--plan-report is only valid with report-events --apply.")
        payload = report_stk_mins_qfq_macd_kdj_repair_completion_events(
            instance=instance,
            qfq_factor_repair_trade_dates=args.trade_dates,
            dry_run=not args.apply,
            expected_plan_fingerprint=expected_plan_fingerprint,
            history_page_limit=args.history_page_limit,
            max_history_records_per_check_key=args.max_history_records_per_check_key,
        ).to_dict()

    output_path = _write_report(args.report_dir, args.stage, payload)
    print(output_path)
    return output_path


def _plan_fingerprint_from_report(plan_report: Path) -> str:
    try:
        payload = json.loads(plan_report.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"plan report does not exist: {plan_report}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"plan report is not valid JSON: {plan_report}") from error
    fingerprint = payload.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError(f"plan report does not contain plan_fingerprint: {plan_report}")
    return fingerprint


def _write_report(report_dir: str, stage: str, payload: dict[str, object]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(report_dir)
        / f"stk_mins_qfq_macd_kdj_repair_completion_events_{stage}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    main()
