from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    audit_wealth_market_turnover_history,
    generate_wealth_market_turnover_history,
    plan_wealth_market_turnover_history,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "profile-history",
            "write-sample",
            "audit-sample",
            "write-full",
            "audit-full",
        ),
    )
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date")
    parser.add_argument("--partition-keys")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--report-dir", default="/private/tmp")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root)
    requested_keys = _csv_values(args.partition_keys)
    duckdb = DuckDBResource()

    if args.stage == "profile-history":
        report = plan_wealth_market_turnover_history(
            lake_root=lake_root,
            partition_keys=requested_keys,
            start_date=args.start_date,
            end_date=args.end_date,
        ).to_dict()
    elif args.stage in {"write-sample", "write-full"}:
        plan = plan_wealth_market_turnover_history(
            lake_root=lake_root,
            partition_keys=requested_keys,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        keys = (
            plan.sample_partition_keys
            if args.stage == "write-sample" and requested_keys is None
            else plan.selected_partition_keys
        )
        if args.apply:
            report = generate_wealth_market_turnover_history(
                lake_root=lake_root,
                duckdb_resource=duckdb,
                partition_keys=keys,
                overwrite=args.overwrite,
            ).to_dict()
        else:
            report = {
                "dry_run": True,
                "selected_partition_keys": list(keys),
                "would_write_count": len(keys),
                "plan": plan.to_dict(),
            }
    elif args.stage in {"audit-sample", "audit-full"}:
        plan = plan_wealth_market_turnover_history(
            lake_root=lake_root,
            partition_keys=requested_keys,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        keys = (
            plan.sample_partition_keys
            if args.stage == "audit-sample" and requested_keys is None
            else plan.selected_partition_keys
        )
        report = audit_wealth_market_turnover_history(
            lake_root=lake_root,
            duckdb_resource=duckdb,
            partition_keys=keys,
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


def _write_report(report_dir: str, stage: str, payload: dict[str, object]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(report_dir)
        / f"wealth_market_turnover_history_{stage}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    main()
