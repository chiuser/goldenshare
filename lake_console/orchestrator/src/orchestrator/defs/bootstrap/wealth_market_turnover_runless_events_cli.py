from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.wealth_market_turnover_runless_events import (
    plan_wealth_market_turnover_runless_events,
    recent_wealth_market_turnover_partitions,
    report_wealth_market_turnover_runless_events,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "plan-events",
            "report-sample-events",
            "audit-sample-events",
            "report-recent-window-events",
            "audit-recent-window-events",
        ),
    )
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--partition-keys")
    parser.add_argument("--history-audit-report-path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", default="/private/tmp")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root)
    duckdb = DuckDBResource()
    instance = dg.DagsterInstance.get()
    requested_keys = _csv_values(args.partition_keys)

    if args.stage in {"report-sample-events", "audit-sample-events"} and requested_keys is None:
        recent_keys = recent_wealth_market_turnover_partitions(lake_root)
        requested_keys = _sample_partition_keys(recent_keys)

    if args.stage in {"plan-events", "audit-sample-events", "audit-recent-window-events"}:
        report = plan_wealth_market_turnover_runless_events(
            instance=instance,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            partition_keys=requested_keys,
            history_audit_report_path=args.history_audit_report_path,
        ).to_dict()
    elif args.stage in {"report-sample-events", "report-recent-window-events"}:
        report = report_wealth_market_turnover_runless_events(
            instance=instance,
            lake_root=lake_root,
            duckdb_resource=duckdb,
            partition_keys=requested_keys,
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


def _sample_partition_keys(partition_keys: tuple[str, ...]) -> tuple[str, ...]:
    if not partition_keys:
        return ()
    return tuple(
        dict.fromkeys(
            (
                partition_keys[0],
                partition_keys[len(partition_keys) // 2],
                partition_keys[-1],
            )
        )
    )


def _write_report(report_dir: str, stage: str, payload: dict[str, object]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(report_dir)
        / f"wealth_market_turnover_runless_events_{stage}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    main()
