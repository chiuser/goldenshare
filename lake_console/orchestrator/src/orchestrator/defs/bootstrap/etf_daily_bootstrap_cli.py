"""Controlled phase runner for ETF daily Direct Lake Bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_apply import (
    EtfDailyBootstrapApplyError,
    run_bounded_sample,
    run_raw_apply,
    run_silver_apply,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_audit import (
    EtfDailyBootstrapAuditError,
    run_physical_post_audit,
    run_raw_audit,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_events import (
    EtfDailyBootstrapEventPlan,
    EtfDailyBootstrapEventsError,
    apply_events,
    build_event_plan,
    load_event_plan,
    post_audit_events,
    write_event_plan,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    BOOTSTRAP_STAGING_ROOT,
    FORMAL_LAKE_ROOT,
    EtfDailyBootstrapPlanError,
    EtfDailySilverBootstrapPlan,
    build_etf_daily_raw_bootstrap_plan,
    build_etf_daily_silver_bootstrap_plan,
    load_etf_daily_raw_bootstrap_plan,
    load_etf_daily_silver_bootstrap_plan,
    load_json,
    write_raw_bootstrap_plan,
    write_silver_bootstrap_plan,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("Bootstrap paths must be absolute")
    return path


def _common_roots(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", type=_absolute_path, required=True)
    parser.add_argument("--staging-root", type=_absolute_path, required=True)


def _raw_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw-plan", type=_absolute_path, required=True)
    parser.add_argument("--expected-raw-plan-hash", required=True)


def _silver_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--silver-plan", type=_absolute_path, required=True)
    parser.add_argument("--expected-silver-plan-hash", required=True)


def _event_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--events-plan", type=_absolute_path, required=True)
    parser.add_argument("--expected-events-plan-hash", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    raw_plan = commands.add_parser("raw-plan")
    _common_roots(raw_plan)
    raw_plan.add_argument("--output", type=_absolute_path, required=True)
    raw_plan.add_argument("--code-revision", required=True)
    raw_plan.add_argument("--operation-id", required=True)
    raw_plan.add_argument("--confirm-raw-plan", action="store_true")

    sample = commands.add_parser("bounded-sample")
    _raw_plan_args(sample)
    sample.add_argument("--source-lake-root", type=_absolute_path, required=True)
    sample.add_argument("--isolated-lake-root", type=_absolute_path, required=True)
    sample.add_argument("--isolated-staging-root", type=_absolute_path, required=True)
    sample.add_argument("--output", type=_absolute_path, required=True)
    sample.add_argument("--confirm-source-request", action="store_true")

    raw_apply = commands.add_parser("raw-apply")
    _raw_plan_args(raw_apply)
    _common_roots(raw_apply)
    raw_apply.add_argument("--checkpoint", type=_absolute_path, required=True)
    raw_apply.add_argument("--output", type=_absolute_path, required=True)
    raw_apply.add_argument("--confirm-raw-apply", action="store_true")

    raw_audit = commands.add_parser("raw-audit")
    _raw_plan_args(raw_audit)
    raw_audit.add_argument("--lake-root", type=_absolute_path, required=True)
    raw_audit.add_argument("--checkpoint", type=_absolute_path, required=True)
    raw_audit.add_argument("--output", type=_absolute_path, required=True)

    silver_plan = commands.add_parser("silver-plan")
    _raw_plan_args(silver_plan)
    _common_roots(silver_plan)
    silver_plan.add_argument("--raw-audit", type=_absolute_path, required=True)
    silver_plan.add_argument("--output", type=_absolute_path, required=True)
    silver_plan.add_argument("--code-revision", required=True)
    silver_plan.add_argument("--coverage-policy-revision", required=True)
    silver_plan.add_argument("--confirm-silver-plan", action="store_true")
    silver_plan.add_argument("--confirm-coverage-review", action="store_true")

    silver_apply = commands.add_parser("silver-apply")
    _raw_plan_args(silver_apply)
    _silver_plan_args(silver_apply)
    _common_roots(silver_apply)
    silver_apply.add_argument("--checkpoint", type=_absolute_path, required=True)
    silver_apply.add_argument("--output", type=_absolute_path, required=True)
    silver_apply.add_argument("--confirm-silver-apply", action="store_true")

    physical = commands.add_parser("physical-post-audit")
    _raw_plan_args(physical)
    _silver_plan_args(physical)
    _common_roots(physical)
    physical.add_argument("--checkpoint", type=_absolute_path, required=True)
    physical.add_argument("--output", type=_absolute_path, required=True)

    events_plan = commands.add_parser("events-plan")
    _silver_plan_args(events_plan)
    events_plan.add_argument("--physical-report", type=_absolute_path, required=True)
    events_plan.add_argument("--output", type=_absolute_path, required=True)

    events_apply = commands.add_parser("events-apply")
    _event_plan_args(events_apply)
    events_apply.add_argument("--checkpoint", type=_absolute_path, required=True)
    events_apply.add_argument("--output", type=_absolute_path, required=True)
    events_apply.add_argument("--confirm-events-apply", action="store_true")

    events_audit = commands.add_parser("events-post-audit")
    _event_plan_args(events_audit)
    events_audit.add_argument("--output", type=_absolute_path, required=True)
    return parser


def _latest_basic(
    *, instance: dg.DagsterInstance, lake_root: Path, duckdb: DuckDBResource
):  # type: ignore[no-untyped-def]
    today = datetime.now(_SHANGHAI).date()
    return select_latest_etf_basic_snapshot_reference(
        instance=instance,
        lake_root_path=lake_root,
        duckdb_resource=duckdb,
        eligibility_as_of=today,
        required_freshness_date=today,
    )


def _confirmation_error(args: argparse.Namespace) -> str | None:
    required = {
        "raw-plan": "confirm_raw_plan",
        "bounded-sample": "confirm_source_request",
        "raw-apply": "confirm_raw_apply",
        "silver-plan": "confirm_silver_plan",
        "silver-apply": "confirm_silver_apply",
        "events-apply": "confirm_events_apply",
    }
    field = required.get(args.command)
    if field is not None and not getattr(args, field):
        return f"{args.command} requires --{field.replace('_', '-')}"
    if args.command == "silver-plan" and not args.confirm_coverage_review:
        return "silver-plan requires --confirm-coverage-review"
    return None


def _require_formal_roots(lake_root: Path, staging_root: Path) -> None:
    if lake_root.resolve() != FORMAL_LAKE_ROOT or staging_root.resolve() != BOOTSTRAP_STAGING_ROOT:
        raise EtfDailyBootstrapPlanError(
            "formal Bootstrap commands require the approved Lake and staging roots"
        )


def _require_bounded_sample_roots(
    *, source_lake_root: Path, isolated_lake_root: Path, isolated_staging_root: Path
) -> None:
    if source_lake_root.resolve() != FORMAL_LAKE_ROOT:
        raise EtfDailyBootstrapPlanError(
            "bounded sample must read Basic only from the approved formal Lake"
        )
    allowed_parents = (Path("/private/tmp"), BOOTSTRAP_STAGING_ROOT)
    for root in (isolated_lake_root.resolve(), isolated_staging_root.resolve()):
        if root == FORMAL_LAKE_ROOT or not any(root.is_relative_to(parent) for parent in allowed_parents):
            raise EtfDailyBootstrapPlanError(
                "bounded sample roots must stay under /private/tmp or approved staging"
            )


def _require_formal_silver_plan(plan: EtfDailySilverBootstrapPlan) -> None:
    paths = tuple(
        Path(item.target_path)
        for items in (plan.raw_manifest, plan.silver_targets)
        for item in items
    )
    if not paths or any(
        not path.is_absolute() or not path.is_relative_to(FORMAL_LAKE_ROOT)
        for path in paths
    ):
        raise EtfDailyBootstrapPlanError(
            "event planning requires a Silver Plan bound to the approved formal Lake"
        )


def _require_formal_event_plan(plan: EtfDailyBootstrapEventPlan) -> None:
    paths = tuple(Path(item.target_path) for item in plan.materializations)
    if not paths or any(
        not path.is_absolute() or not path.is_relative_to(FORMAL_LAKE_ROOT)
        for path in paths
    ):
        raise EtfDailyBootstrapPlanError(
            "event commands require physical evidence from the approved formal Lake"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    error = _confirmation_error(args)
    if error:
        print(error, file=sys.stderr)
        return 2
    duckdb = DuckDBResource()
    try:
        with dg.DagsterInstance.get() as instance:
            result = _run(args=args, instance=instance, duckdb=duckdb)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 3 if result.get("should_stop") is True or result.get("passed") is False else 0
    except (
        EtfDailyBootstrapApplyError,
        EtfDailyBootstrapAuditError,
        EtfDailyBootstrapEventsError,
        EtfDailyBootstrapPlanError,
        RuntimeError,
        ValueError,
    ) as stopped:
        print(f"ETF daily Bootstrap stopped: {stopped}", file=sys.stderr)
        return 3


def _run(
    *, args: argparse.Namespace, instance: dg.DagsterInstance, duckdb: DuckDBResource
) -> dict[str, object]:
    if args.command == "raw-plan":
        _require_formal_roots(args.lake_root, args.staging_root)
        plan = build_etf_daily_raw_bootstrap_plan(
            instance=instance,
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            code_revision=args.code_revision,
            operation_id=args.operation_id,
        )
        write_raw_bootstrap_plan(plan, args.output)
        return plan.to_dict()
    if args.command == "bounded-sample":
        _require_bounded_sample_roots(
            source_lake_root=args.source_lake_root,
            isolated_lake_root=args.isolated_lake_root,
            isolated_staging_root=args.isolated_staging_root,
        )
        plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        return run_bounded_sample(
            raw_plan=plan,
            isolated_lake_root=args.isolated_lake_root,
            isolated_staging_root=args.isolated_staging_root,
            duckdb_resource=duckdb,
            tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
            basic_reference=_latest_basic(
                instance=instance, lake_root=args.source_lake_root, duckdb=duckdb
            ),
            output_path=args.output,
        )
    if args.command == "raw-apply":
        _require_formal_roots(args.lake_root, args.staging_root)
        plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        return run_raw_apply(
            raw_plan=plan,
            instance=instance,
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            tushare=TushareResource(token=os.environ.get("TUSHARE_TOKEN", "")),
            checkpoint_path=args.checkpoint,
            output_path=args.output,
            confirm_raw_apply=True,
        )
    if args.command == "raw-audit":
        if args.lake_root.resolve() != FORMAL_LAKE_ROOT:
            raise EtfDailyBootstrapPlanError(
                "Raw audit requires the approved formal Lake root"
            )
        plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        return run_raw_audit(
            raw_plan=plan,
            lake_root=args.lake_root,
            duckdb_resource=duckdb,
            checkpoint_path=args.checkpoint,
            latest_basic_reference=_latest_basic(
                instance=instance, lake_root=args.lake_root, duckdb=duckdb
            ),
            output_path=args.output,
        )
    if args.command == "silver-plan":
        _require_formal_roots(args.lake_root, args.staging_root)
        raw_plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        raw_audit = load_json(args.raw_audit, label="ETF daily Raw audit")
        plan = build_etf_daily_silver_bootstrap_plan(
            raw_plan=raw_plan,
            raw_audit_report=raw_audit,
            basic_reference=_latest_basic(
                instance=instance, lake_root=args.lake_root, duckdb=duckdb
            ),
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            code_revision=args.code_revision,
            coverage_policy_revision=args.coverage_policy_revision,
            coverage_review_confirmed=args.confirm_coverage_review,
        )
        write_silver_bootstrap_plan(plan, args.output)
        return plan.to_dict()
    if args.command == "silver-apply":
        _require_formal_roots(args.lake_root, args.staging_root)
        raw_plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        silver_plan = load_etf_daily_silver_bootstrap_plan(
            args.silver_plan, expected_plan_hash=args.expected_silver_plan_hash
        )
        return run_silver_apply(
            silver_plan=silver_plan,
            raw_plan=raw_plan,
            latest_basic_reference=_latest_basic(
                instance=instance, lake_root=args.lake_root, duckdb=duckdb
            ),
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            checkpoint_path=args.checkpoint,
            output_path=args.output,
            confirm_silver_apply=True,
        )
    if args.command == "physical-post-audit":
        _require_formal_roots(args.lake_root, args.staging_root)
        raw_plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        silver_plan = load_etf_daily_silver_bootstrap_plan(
            args.silver_plan, expected_plan_hash=args.expected_silver_plan_hash
        )
        return run_physical_post_audit(
            raw_plan=raw_plan,
            silver_plan=silver_plan,
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            checkpoint_path=args.checkpoint,
            output_path=args.output,
        )
    if args.command == "events-plan":
        silver_plan = load_etf_daily_silver_bootstrap_plan(
            args.silver_plan, expected_plan_hash=args.expected_silver_plan_hash
        )
        _require_formal_silver_plan(silver_plan)
        plan = build_event_plan(
            instance=instance,
            silver_plan=silver_plan,
            physical_report_path=args.physical_report,
        )
        write_event_plan(plan, args.output)
        return plan.to_dict()
    plan = load_event_plan(
        args.events_plan, expected_plan_hash=args.expected_events_plan_hash
    )
    _require_formal_event_plan(plan)
    if args.command == "events-apply":
        return apply_events(
            instance=instance,
            plan=plan,
            checkpoint_path=args.checkpoint,
            output_path=args.output,
            confirm_events_apply=True,
        )
    if args.command == "events-post-audit":
        return post_audit_events(instance=instance, plan=plan, output_path=args.output)
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
