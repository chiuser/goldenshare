"""Inspect, compare, and publish approved suspension facts, by manual operation.

No CSV conversion, arbitrary path option, asset execution or event registration.
File and event approval are separate; these commands never construct an instance.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path


def _parser():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "compare", "publish-file"):
        child = commands.add_parser(command, allow_abbrev=False)
        child.add_argument("--operation-id", required=True)
        if command != "inspect":
            child.add_argument("--expected-plan-sha256", required=True)
        if command == "compare":
            child.add_argument("--save-report", action="store_true")
        if command == "publish-file":
            child.add_argument("--expected-comparison-sha256", required=True)
            child.add_argument("--confirm-file-publish", action="store_true")
    return parser


def _emit(mode, applied, **values):
    print(json.dumps({"mode": mode, "applied": applied, **values}, ensure_ascii=False), flush=True)


def main(argv=None, *, lake_root=None, staging_root=None, connection_settings=None):
    # Keyword-only dependencies support isolated tests, never operator options.
    # Help/invalid arguments finish before importing any connection/file helper.
    if argv is None:
        import sys
        argv = sys.argv[1:]
    parser = _parser()
    if not argv:
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        if error.code:
            _emit("readonly", False, reason_code="invalid_arguments")
        return int(error.code)

    from duckdb import Error as DuckDBError

    from orchestrator.defs import stock_suspend_confirmed_contract as contract
    from orchestrator.defs.bootstrap import stock_suspend_confirmed as publication
    from orchestrator.defs.duckdb_connection import (
        DEFAULT_DUCKDB_CONNECTION_SETTINGS,
        connect_configured_duckdb,
    )
    from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT

    mode = "apply" if (getattr(args, "save_report", False) or
                       getattr(args, "confirm_file_publish", False)) else "readonly"
    applied = False
    try:
        paths = publication.PublicationPaths(
            Path(lake_root if lake_root is not None else DEFAULT_LAKE_ROOT),
            Path(staging_root if staging_root is not None else DEFAULT_LAKE_STAGING_ROOT), args.operation_id,
        )
        # Reject malformed expected hashes before touching paths or connecting.
        for key in ("expected_plan_sha256", "expected_comparison_sha256"):
            if hasattr(args, key):
                publication._hash(getattr(args, key))
        plan = publication.read_confirmed_plan(
            paths=paths, expected_plan_sha256=getattr(args, "expected_plan_sha256", None))
        comparison = None
        if args.command == "publish-file":
            comparison = publication.read_confirmed_comparison(
                plan=plan, expected_comparison_sha256=args.expected_comparison_sha256)
        settings = connection_settings if connection_settings is not None else DEFAULT_DUCKDB_CONNECTION_SETTINGS
        with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
            if args.command == "inspect":
                result = asdict(publication.inspect_confirmed_publication(connection, paths=paths))
            elif args.command == "compare":
                comparison = publication.compare_confirmed_migration(connection, plan=plan)
                if args.save_report:
                    comparison = publication.save_confirmed_comparison(plan=plan, comparison=comparison)
                    applied = True
                result = {**comparison.payload(), "passed": comparison.passed,
                          "report_sha256": comparison.report_sha256}
                _emit(mode, applied, **result)
                return 0 if comparison.passed else 3
            elif args.confirm_file_publish:
                result = asdict(publication.publish_confirmed_file(connection, plan=plan, comparison=comparison))
                applied = True
            else:
                status = publication.validate_confirmed_file_publication(connection, plan=plan, comparison=comparison)
                result = {"planned_action": status, "target_path": str(paths.target),
                          "plan_sha256": plan.sha256, "comparison_sha256": comparison.report_sha256}
        _emit(mode, applied, **result)
        return 0
    except contract.ConfirmedFactsError as error:
        _emit(mode, applied, reason_code=error.reason_code, message=str(error),
              file_may_be_committed=error.exit_code == 5)
        return error.exit_code
    except (ValueError, TypeError, KeyError) as error:
        _emit(mode, applied, reason_code="invalid_document_or_argument", message=type(error).__name__)
        return 2
    except (OSError, RuntimeError, DuckDBError) as error:
        _emit(mode, applied, reason_code="io_or_query_failed", message=type(error).__name__)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
