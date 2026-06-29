from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_events import (
    plan_gold_stock_daily_qfq_runless_events,
    report_gold_stock_daily_qfq_runless_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=("plan-events", "report-events"),
    )
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--as-of-trade-date")
    parser.add_argument("--materialization-partition-keys")
    parser.add_argument("--check-partition-keys")
    parser.add_argument("--history-audit-report-path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", default="/private/tmp")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root)
    as_of_trade_date = _require_as_of_trade_date(parser, args.as_of_trade_date)
    duckdb_resource = DuckDBResource()
    instance = dg.DagsterInstance.get()
    materialization_keys = _csv_values(args.materialization_partition_keys)
    check_keys = _csv_values(args.check_partition_keys)

    if args.stage == "plan-events":
        report = plan_gold_stock_daily_qfq_runless_events(
            instance=instance,
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            qfq_as_of_trade_date=as_of_trade_date,
            materialization_partition_keys=materialization_keys,
            check_partition_keys=check_keys,
        ).to_dict()
    elif args.stage == "report-events":
        report = report_gold_stock_daily_qfq_runless_events(
            instance=instance,
            lake_root=lake_root,
            duckdb_resource=duckdb_resource,
            qfq_as_of_trade_date=as_of_trade_date,
            materialization_partition_keys=materialization_keys,
            check_partition_keys=check_keys,
            history_audit_report_path=args.history_audit_report_path,
            dry_run=not args.apply,
        ).to_dict()
    else:
        raise ValueError(f"Unsupported stage: {args.stage}")

    output_path = _write_report(args.report_dir, args.stage, report)
    print(output_path)
    return output_path


def _csv_values(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _require_as_of_trade_date(
    parser: argparse.ArgumentParser,
    value: str | None,
) -> str:
    if not value or not value.strip():
        parser.error(
            "--as-of-trade-date is required for gold_stock_daily_qfq runless events"
        )
    return value.strip()


def _write_report(report_dir: str, stage: str, payload: dict[str, object]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(report_dir) / f"gold_stock_daily_qfq_history_events_{stage}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    main()
