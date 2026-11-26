"""Controlled phase runner for ETF daily Direct Lake Bootstrap."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    EtfBasicReadinessError,
    select_historical_etf_basic_snapshot_reference,
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.assets.etf_basic import raw_tushare_etf_basic, silver_etf_basic
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
    EtfDailyRawBootstrapPlan,
    EtfDailySilverBootstrapPlan,
    build_etf_daily_raw_bootstrap_plan,
    build_etf_daily_silver_bootstrap_plan,
    load_etf_daily_raw_bootstrap_plan,
    load_etf_daily_silver_bootstrap_plan,
    load_json,
    write_raw_bootstrap_plan,
    write_silver_bootstrap_plan,
)
from orchestrator.defs.bootstrap.etf_daily_history_source import prepare_history_source
from orchestrator.defs.confirmed_business_facts import FactType
from orchestrator.defs.resources import (
    ConfirmedBusinessFactsResource,
    DuckDBResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.etf_basic import EtfBasicSilverSnapshotReference
from orchestrator.defs.run_contracts.etf_mins import etf_sensor_window_is_open

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
    raw_plan.add_argument("--history-2023-2024", action="store_true")

    source = commands.add_parser("history-source")
    _raw_plan_args(source)
    _common_roots(source)
    source.add_argument("--prod-timeout-seconds", required=True, type=int)
    source.add_argument("--tushare-daily-date", action="append", default=[])
    source.add_argument("--confirm-prod-export", action="store_true")

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
    raw_apply.add_argument("--first-batch", action="store_true")
    raw_apply.add_argument("--tushare-daily-date", action="append", default=[])

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

    for command in (raw_audit, silver_plan):
        command.add_argument("--first-batch", action="store_true")
        command.add_argument("--first-silver-plan", type=_absolute_path)
        command.add_argument("--expected-first-silver-plan-hash")

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
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    evaluated_at: datetime | None = None,
) -> EtfBasicSilverSnapshotReference:
    """Validate the latest Basic against its daily refresh window, not midnight."""
    now = evaluated_at or datetime.now(_SHANGHAI)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Bootstrap Basic evaluated_at must include a timezone")
    now = now.astimezone(_SHANGHAI)
    earliest_date = now.date()
    if not etf_sensor_window_is_open(now):
        earliest_date -= timedelta(days=1)
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=raw_tushare_etf_basic.key), limit=1
    ).records
    if not records:
        raise EtfBasicReadinessError(
            "etf_basic_latest_materialization_missing: raw_tushare_etf_basic."
        )
    materialization = records[0].asset_materialization
    if materialization is None:
        raise EtfBasicReadinessError("etf_basic_materialization_payload_missing.")
    metadata = materialization.metadata
    observed_value = metadata.get("goldenshare/observed_at")
    observed_value = getattr(observed_value, "value", observed_value)
    if not isinstance(observed_value, str) or not observed_value:
        raise EtfBasicReadinessError("etf_basic_raw_observed_at_missing.")
    try:
        observed_at = datetime.fromisoformat(observed_value)
    except ValueError as error:
        raise EtfBasicReadinessError("etf_basic_raw_observed_at_invalid.") from error
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise EtfBasicReadinessError(
            "etf_basic_raw_observed_at_invalid: timezone required."
        )
    observed_date = observed_at.astimezone(_SHANGHAI).date()
    if observed_at > now or observed_date < earliest_date:
        raise EtfBasicReadinessError(
            "etf_basic_raw_observed_at_outside_refresh_window: "
            f"observed_at={observed_at.isoformat()}, earliest_date={earliest_date}, "
            f"evaluated_at={now.isoformat()}."
        )
    reference = select_latest_etf_basic_snapshot_reference(
        instance=instance,
        lake_root_path=lake_root,
        duckdb_resource=duckdb,
        eligibility_as_of=observed_date,
        required_freshness_date=observed_date,
    )
    snapshot_hash = metadata.get("goldenshare/raw_snapshot_hash")
    if (
        reference.raw_snapshot_hash != getattr(snapshot_hash, "value", snapshot_hash)
        or datetime.fromisoformat(reference.raw_observed_at) != observed_at
    ):
        raise EtfBasicReadinessError("etf_basic_changed_during_bootstrap_selection.")
    return reference


def _check_frozen_basic(
    instance: dg.DagsterInstance,
    lake_root: Path,
    duckdb: DuckDBResource,
    reference: EtfBasicSilverSnapshotReference,
    storage_ids: tuple[int, int],
) -> EtfBasicSilverSnapshotReference:
    verified = select_historical_etf_basic_snapshot_reference(
        instance=instance,
        lake_root_path=lake_root,
        duckdb_resource=duckdb,
        trade_date=date.fromisoformat(reference.eligibility_as_of),
        raw_storage_id=storage_ids[0],
        silver_storage_id=storage_ids[1],
    )
    if verified.reference_fingerprint != reference.reference_fingerprint:
        raise EtfDailyBootstrapPlanError("frozen Basic evidence has changed")
    return verified


def _planning_basic(
    args: argparse.Namespace,
    instance: dg.DagsterInstance,
    duckdb: DuckDBResource,
    raw_plan: EtfDailyRawBootstrapPlan,
) -> tuple[EtfBasicSilverSnapshotReference, tuple[int, int] | None]:
    first_plan_path = args.first_silver_plan
    first_plan_hash = args.expected_first_silver_plan_hash
    if bool(first_plan_path) != bool(first_plan_hash):
        raise EtfDailyBootstrapPlanError(
            "first Silver plan and hash must be provided together"
        )
    if not raw_plan.historical:
        if first_plan_path or args.first_batch:
            raise EtfDailyBootstrapPlanError(
                "first batch options require the 2023–2024 plan"
            )
        return _latest_basic(
            instance=instance, lake_root=args.lake_root, duckdb=duckdb
        ), None
    if first_plan_path:
        if args.first_batch:
            raise EtfDailyBootstrapPlanError(
                "only the full plan can inherit the first Silver plan"
            )
        prior = load_etf_daily_silver_bootstrap_plan(
            first_plan_path, expected_plan_hash=first_plan_hash
        )
        if (
            not prior.historical
            or prior.parent_raw_plan_hash != raw_plan.raw_plan_hash
            or prior.trade_dates != raw_plan.selected_dates(first_batch=True)
            or prior.basic_storage_ids is None
        ):
            raise EtfDailyBootstrapPlanError(
                "first Silver plan does not match this historical operation"
            )
        return (
            _check_frozen_basic(
                instance,
                args.lake_root,
                duckdb,
                prior.basic_reference,
                prior.basic_storage_ids,
            ),
            prior.basic_storage_ids,
        )
    if not args.first_batch and raw_plan.trade_dates != raw_plan.selected_dates(
        first_batch=True
    ):
        raise EtfDailyBootstrapPlanError(
            "the full scope requires the first Silver plan"
        )
    records = []
    for asset in (raw_tushare_etf_basic, silver_etf_basic):
        latest = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset.key), limit=1
        ).records
        if not latest:
            raise EtfDailyBootstrapPlanError(
                "historical plan requires checked ETF Basic evidence"
            )
        records.append(latest[0].storage_id)
    storage_ids = (records[0], records[1])
    reference = _latest_basic(
        instance=instance, lake_root=args.lake_root, duckdb=duckdb
    )
    return _check_frozen_basic(
        instance, args.lake_root, duckdb, reference, storage_ids
    ), storage_ids


def _historical_liquidating_codes(dates: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    start = date.fromisoformat(dates[0])
    end = date.fromisoformat(dates[-1]) + timedelta(days=1)
    facts = ConfirmedBusinessFactsResource().read_facts(
        subject_type="etf",
        fact_types=(FactType.FUND_LIQUIDATION_STARTED,),
        window_start=start,
        window_end_exclusive=end,
    )
    result = {}
    for key in dates:
        day = datetime.combine(date.fromisoformat(key), time.min, tzinfo=_SHANGHAI)
        codes = {
            fact.subject_key
            for fact in facts
            if fact.effective_from < (day + timedelta(days=1))
            and (fact.effective_until is None or fact.effective_until > day)
        }
        if codes:
            result[key] = tuple(sorted(codes))
    return result


def _confirmation_error(args: argparse.Namespace) -> str | None:
    required = {
        "raw-plan": "confirm_raw_plan",
        "history-source": "confirm_prod_export",
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
    if (
        lake_root.resolve() != FORMAL_LAKE_ROOT
        or staging_root.resolve() != BOOTSTRAP_STAGING_ROOT
    ):
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
        if root == FORMAL_LAKE_ROOT or not any(
            root.is_relative_to(parent) for parent in allowed_parents
        ):
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
        return (
            3
            if result.get("should_stop") is True or result.get("passed") is False
            else 0
        )
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
            historical=args.history_2023_2024,
        )
        write_raw_bootstrap_plan(plan, args.output)
        return plan.to_dict()
    if args.command == "history-source":
        _require_formal_roots(args.lake_root, args.staging_root)
        plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        source = prepare_history_source(
            staging_root=args.staging_root,
            plan=plan,
            duckdb=duckdb,
            tushare_dates=args.tushare_daily_date,
            timeout_seconds=args.prod_timeout_seconds,
        )
        return {
            "source_path": str(source.path),
            "source_fingerprint": source.fingerprint,
            "row_count": sum(source.row_counts.values()),
            "prod_day_count": len(source.row_counts),
            "tushare_dates": sorted(source.tushare_dates),
            "fetched_at": source.fetched_at,
        }
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
            first_batch=args.first_batch,
            tushare_dates=args.tushare_daily_date,
        )
    if args.command == "raw-audit":
        if args.lake_root.resolve() != FORMAL_LAKE_ROOT:
            raise EtfDailyBootstrapPlanError(
                "Raw audit requires the approved formal Lake root"
            )
        plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        basic, _ = _planning_basic(args, instance, duckdb, plan)
        return run_raw_audit(
            raw_plan=plan,
            lake_root=args.lake_root,
            duckdb_resource=duckdb,
            checkpoint_path=args.checkpoint,
            latest_basic_reference=basic,
            first_batch=args.first_batch,
            output_path=args.output,
        )
    if args.command == "silver-plan":
        _require_formal_roots(args.lake_root, args.staging_root)
        raw_plan = load_etf_daily_raw_bootstrap_plan(
            args.raw_plan, expected_plan_hash=args.expected_raw_plan_hash
        )
        raw_audit = load_json(args.raw_audit, label="ETF daily Raw audit")
        basic, storage_ids = _planning_basic(args, instance, duckdb, raw_plan)
        plan = build_etf_daily_silver_bootstrap_plan(
            raw_plan=raw_plan,
            raw_audit_report=raw_audit,
            basic_reference=basic,
            basic_storage_ids=storage_ids,
            first_batch=args.first_batch,
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
            latest_basic_reference=(
                _check_frozen_basic(
                    instance,
                    args.lake_root,
                    duckdb,
                    silver_plan.basic_reference,
                    silver_plan.basic_storage_ids,
                )
                if silver_plan.basic_storage_ids is not None
                else _latest_basic(
                    instance=instance, lake_root=args.lake_root, duckdb=duckdb
                )
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
        liquidating_codes = None
        if silver_plan.historical:
            if silver_plan.basic_storage_ids is None:
                raise EtfDailyBootstrapPlanError("missing frozen Basic evidence")
            _check_frozen_basic(
                instance,
                args.lake_root,
                duckdb,
                silver_plan.basic_reference,
                silver_plan.basic_storage_ids,
            )
            liquidating_codes = _historical_liquidating_codes(silver_plan.trade_dates)
        return run_physical_post_audit(
            raw_plan=raw_plan,
            silver_plan=silver_plan,
            lake_root=args.lake_root,
            staging_root=args.staging_root,
            duckdb_resource=duckdb,
            checkpoint_path=args.checkpoint,
            output_path=args.output,
            liquidating_codes_by_date=liquidating_codes,
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
