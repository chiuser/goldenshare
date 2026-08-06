"""Temporary-lake build, audit, and explicit formal promote for Bootstrap."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_apply import (
    MajorIndexMinsBootstrapApplyError,
    audit_temporary_lake,
    build_temporary_lake_from_staging,
    promote_temporary_lake,
    write_target_audit,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsBootstrapPlanError,
    build_date_plan,
    build_source_plan,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.resources import DuckDBResource


def _default_output(prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/private/tmp/major_index_mins_{prefix}_{stamp}.json")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--calendar-lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT)
    )
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build from retained source staging; this CLI never calls Tushare."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-temp")
    _common(build)
    build.add_argument("--confirm-staging-write", action="store_true")
    audit = subparsers.add_parser("audit-temp")
    _common(audit)
    promote = subparsers.add_parser("promote")
    _common(promote)
    promote.add_argument(
        "--formal-lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT)
    )
    promote.add_argument("--confirm-lake-write", action="store_true")
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
    if args.command == "build-temp" and not args.confirm_staging_write:
        print("temporary lake writes require --confirm-staging-write", file=sys.stderr)
        return 2
    if args.command == "promote" and not args.confirm_lake_write:
        print("formal lake writes require --confirm-lake-write", file=sys.stderr)
        return 2
    try:
        duckdb_resource, date_plan, source_plan = _plans(
            lake_root=args.calendar_lake_root,
            end_date=args.end_date,
        )
        if args.command == "build-temp":
            output = args.output or _default_output("temporary_lake_build")
            report = build_temporary_lake_from_staging(
                staging_root=args.staging_root,
                date_plan=date_plan,
                source_plan=source_plan,
                duckdb_resource=duckdb_resource,
                output_path=output,
            )
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0 if not report.should_stop else 3
        if args.command == "audit-temp":
            output = args.output or _default_output("temporary_lake_audit")
            audits = audit_temporary_lake(
                staging_root=args.staging_root,
                date_plan=date_plan,
                duckdb_resource=duckdb_resource,
            )
            write_target_audit(audits, output)
            ready = all(
                audit.missing_count == 0 and audit.invalid_existing_count == 0
                for audit in audits
            )
            print(output)
            print(f"ready={ready}")
            return 0 if ready else 3
        if args.command == "promote":
            output = args.output or _default_output("formal_lake_promote")
            report = promote_temporary_lake(
                staging_root=args.staging_root,
                formal_lake_root=args.formal_lake_root,
                date_plan=date_plan,
                source_plan=source_plan,
                duckdb_resource=duckdb_resource,
                output_path=output,
            )
            print(output)
            print(f"should_stop={report.should_stop}")
            return 0 if not report.should_stop else 3
        raise AssertionError("unsupported command")
    except (
        MajorIndexMinsBootstrapApplyError,
        MajorIndexMinsBootstrapPlanError,
    ) as error:
        print(f"major_index_mins Bootstrap stopped: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
