"""Explicit source-staging and request-free audit CLI for major-index minutes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsBootstrapPlanError,
    build_date_plan,
    build_source_plan,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage import (
    MajorIndexMinsBootstrapStageError,
    audit_source_staging,
    stage_source_windows,
    write_source_staging_audit,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource, TushareResource


def _default_output(prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/private/tmp/major_index_mins_{prefix}_{stamp}.json")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recoverable major-index minute source staging; no formal lake writes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage-source")
    _common(stage)
    stage.add_argument("--confirm-source-request", action="store_true")
    audit = subparsers.add_parser("audit-staging")
    _common(audit)
    return parser


def _plans(*, lake_root: Path, end_date: str | None):
    duckdb_resource = DuckDBResource()
    with duckdb_resource.connect() as connection:
        date_plan = build_date_plan(
            connection=connection,
            lake_root=lake_root,
            end_date=end_date,
        )
    return duckdb_resource, date_plan, build_source_plan(date_plan)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "stage-source" and not args.confirm_source_request:
        print("source requests require --confirm-source-request", file=sys.stderr)
        return 2
    try:
        duckdb_resource, date_plan, source_plan = _plans(
            lake_root=args.lake_root,
            end_date=args.end_date,
        )
        if args.command == "stage-source":
            output = args.output or _default_output("source_stage")
            report = stage_source_windows(
                staging_root=args.staging_root,
                date_plan=date_plan,
                source_plan=source_plan,
                tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
                duckdb_resource=duckdb_resource,
                output_path=output,
            )
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0 if not report.should_stop else 3
        if args.command == "audit-staging":
            output = args.output or _default_output("source_staging_audit")
            report = audit_source_staging(
                staging_root=args.staging_root,
                date_plan=date_plan,
                source_plan=source_plan,
                duckdb_resource=duckdb_resource,
            )
            write_source_staging_audit(report, output)
            print(output)
            print(f"transport_ready={report.transport_ready}")
            print(f"business_contract_ready={report.business_contract_ready}")
            return 0 if report.transport_ready else 3
        raise AssertionError("unsupported command")
    except (
        MajorIndexMinsBootstrapPlanError,
        MajorIndexMinsBootstrapStageError,
    ) as error:
        print(f"major_index_mins source staging stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
