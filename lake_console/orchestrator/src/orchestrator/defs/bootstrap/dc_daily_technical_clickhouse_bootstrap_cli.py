"""Bounded Bootstrap planner, sample loader and guarded formal apply."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap import (
    BOOTSTRAP_BATCH_SIZE,
    DcDailyTechnicalClickHouseBootstrapError,
    audit_sample_staging,
    build_gold_dc_daily_technical_bootstrap_plan,
    clickhouse_resource_from_env,
    insert_sample_rows,
    iter_gold_clickhouse_rows,
    write_bootstrap_report,
)
from orchestrator.defs.bootstrap.dc_daily_technical_clickhouse_bootstrap_apply import (
    apply_gold_dc_daily_technical,
    prepare_apply_target,
    validate_apply_request,
)
from orchestrator.defs.resources import DuckDBResource


def _default_output(mode: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"/private/tmp/dc_daily_technical_clickhouse_{mode}_{stamp}.json")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", required=True, type=Path)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--batch-size", type=int, default=BOOTSTRAP_BATCH_SIZE)
    parser.add_argument("--output", type=Path, default=None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan Gold board technical ClickHouse serving without Dagster events. "
            "Formal apply requires explicit target and safety confirmations."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("dry-run", "audit"):
        command_parser = subparsers.add_parser(command)
        _common(command_parser)

    sample = subparsers.add_parser("sample")
    _common(sample)
    sample.add_argument("--staging-table", required=True)
    sample.add_argument("--confirm-sample-write", action="store_true", required=True)
    sample.add_argument("--clickhouse-env-prefix", default="CLICKHOUSE")

    apply = subparsers.add_parser("apply")
    _common(apply)
    apply.add_argument("--target", choices=("local", "prod", "both"), required=True)
    apply.add_argument("--plan-fingerprint", required=True)
    apply.add_argument("--staging-table", required=True)
    apply.add_argument("--run-id", required=True)
    apply.add_argument("--writer-env-prefix", required=True)
    apply.add_argument("--admin-env-prefix", required=True)
    apply.add_argument("--prod-writer-env-prefix", default=None)
    apply.add_argument("--prod-admin-env-prefix", default=None)
    apply.add_argument("--confirm-clickhouse-write", action="store_true", required=True)
    apply.add_argument("--confirm-target-empty", action="store_true", required=True)

    return parser


def _plan(args: argparse.Namespace):
    with DuckDBResource().connect() as connection:
        return build_gold_dc_daily_technical_bootstrap_plan(
            connection=connection,
            lake_root=args.lake_root,
            start_date=args.start_date,
            end_date=args.end_date,
            batch_size=args.batch_size,
        )


def _run_sample(args: argparse.Namespace) -> dict[str, object]:
    if args.start_date is None or args.end_date is None:
        raise ValueError("sample requires --start-date and --end-date")
    plan = _plan(args)
    if plan.should_stop:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "sample stopped because the source plan is not green"
        )
    if len(plan.expected_trade_dates) > 3:
        raise ValueError("sample date range must contain at most 3 trade dates")
    resource = clickhouse_resource_from_env(args.clickhouse_env_prefix)
    with DuckDBResource().connect() as connection:
        rows = iter_gold_clickhouse_rows(
            connection=connection,
            lake_root=args.lake_root,
            trade_dates=plan.expected_trade_dates,
            batch_size=args.batch_size,
        )
        with resource.get_connection() as client:
            sample_result = insert_sample_rows(
                client=client,
                staging_table=args.staging_table,
                row_batches=rows,
            )
            sample_result["audit"] = audit_sample_staging(
                client=client,
                staging_table=args.staging_table,
                expected_rows_by_date={
                    trade_date: plan.audits[trade_date].checked_row_count
                    for trade_date in plan.expected_trade_dates
                },
            )
    return {
        "schema_version": 1,
        "mode": "sample",
        "confirmed": True,
        "plan": plan.to_dict(),
        "sample": sample_result,
    }


def _run_apply(args: argparse.Namespace) -> dict[str, object]:
    plan = _plan(args)
    if plan.should_stop:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "apply stopped because the source plan is not green"
        )
    if plan.plan_fingerprint != args.plan_fingerprint:
        raise DcDailyTechnicalClickHouseBootstrapError(
            "apply stopped because the current source plan fingerprint changed"
        )
    validate_apply_request(
        target=args.target,
        expected_plan_fingerprint=args.plan_fingerprint,
        actual_plan_fingerprint=plan.plan_fingerprint,
        confirm_clickhouse_write=args.confirm_clickhouse_write,
        confirm_target_empty=args.confirm_target_empty,
        run_id=args.run_id,
    )
    expected_rows_by_date = {
        trade_date: plan.audits[trade_date].checked_row_count
        for trade_date in plan.expected_trade_dates
    }
    targets = ("local", "prod") if args.target == "both" else (args.target,)
    results: list[dict[str, object]] = []
    with DuckDBResource().connect() as connection:
        for target in targets:
            writer_prefix, admin_prefix = _target_env_prefixes(args, target)
            writer_resource = clickhouse_resource_from_env(writer_prefix)
            admin_resource = clickhouse_resource_from_env(admin_prefix)
            with admin_resource.get_connection() as admin_client:
                prepared_staging = prepare_apply_target(
                    admin_client,
                    args.staging_table,
                )
                with writer_resource.get_connection() as writer_client:
                    result = apply_gold_dc_daily_technical(
                        source_connection=connection,
                        writer_client=writer_client,
                        admin_client=admin_client,
                        lake_root=args.lake_root,
                        trade_dates=plan.expected_trade_dates,
                        expected_rows_by_date=expected_rows_by_date,
                        plan_fingerprint=plan.plan_fingerprint,
                        expected_plan_fingerprint=args.plan_fingerprint,
                        staging_table=args.staging_table,
                        run_id=args.run_id,
                        confirm_clickhouse_write=args.confirm_clickhouse_write,
                        confirm_target_empty=args.confirm_target_empty,
                        batch_size=args.batch_size,
                        target_name=target,
                        prepared_staging_table=prepared_staging,
                    )
                results.append(result.to_dict())
    return {
        "schema_version": 1,
        "mode": "apply",
        "target": args.target,
        "plan": plan.to_dict(),
        "results": results,
    }


def _target_env_prefixes(
    args: argparse.Namespace,
    target: str,
) -> tuple[str, str]:
    if args.target == "both" and target == "prod":
        if not args.prod_writer_env_prefix or not args.prod_admin_env_prefix:
            raise ValueError(
                "both requires --prod-writer-env-prefix and --prod-admin-env-prefix"
            )
        return args.prod_writer_env_prefix, args.prod_admin_env_prefix
    return args.writer_env_prefix, args.admin_env_prefix


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {"dry-run", "audit"}:
            plan = _plan(args)
            output = args.output or _default_output(args.command)
            write_bootstrap_report(plan, output)
            print(output)
            print(f"should_stop={plan.should_stop}")
            return 0 if not plan.should_stop else 3

        if args.command == "sample":
            report = _run_sample(args)
            output = args.output or _default_output("sample")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            print(output)
            print("should_stop=False")
            return 0
        if args.command == "apply":
            report = _run_apply(args)
            output = args.output or _default_output("apply")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            print(output)
            print("should_stop=False")
            return 0
    except (DcDailyTechnicalClickHouseBootstrapError, RuntimeError, ValueError, OSError) as error:
        print(f"dc daily technical ClickHouse Bootstrap stopped: {error}", file=sys.stderr)
        return 2
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
