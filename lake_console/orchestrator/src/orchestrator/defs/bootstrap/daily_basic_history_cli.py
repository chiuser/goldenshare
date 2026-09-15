"""Offline history CLI; file publication and state writes are separate stages."""

import argparse
import fcntl
import json
import os
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path

from orchestrator.defs.bootstrap.daily_basic_history import (
    LIMIT_NAMES,
    audit_daily_basic_history,
    build_daily_basic_history,
    export_daily_basic_history,
    history_cost_estimate,
    load_history_report,
    make_history_plan,
    promote_daily_basic_history,
    save_history_report,
)
from orchestrator.defs.daily_basic_contract import DailyBasicValidationError
from orchestrator.defs.daily_basic_raw_io import file_sha256
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.daily_basic import DailyBasicHistorySource
from orchestrator.defs.resources import ProdPostgresResource


def history_parser():
    parser = argparse.ArgumentParser(
        description="每日指标离线历史工具；默认不写正式数据"
    )
    parser.add_argument(
        "stage",
        choices=(
            "plan",
            "export",
            "build",
            "audit",
            "promote",
            "plan-events",
            "register",
            "report-events",
            "audit-events",
        ),
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument("--promote-report", type=Path)
    parser.add_argument("--event-plan", type=Path)
    parser.add_argument("--sample-date")
    parser.add_argument("--fingerprint")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--batch-id")
    parser.add_argument("--cost-evidence", type=Path)
    parser.add_argument("--apply", action="store_true")
    for name in LIMIT_NAMES:
        parser.add_argument("--" + name.replace("_", "-"), type=int)
    return parser


def run_history_cli(args):
    report = args.report.absolute()
    if not report.resolve().is_relative_to(Path("/private/tmp")):
        raise DailyBasicValidationError("history_report_requires_private_tmp")
    if any(
        path is not None and path.resolve() == report.resolve()
        for path in (
            args.plan,
            args.audit_report,
            args.cost_evidence,
            args.promote_report,
            args.event_plan,
        )
    ):
        raise DailyBasicValidationError("history_report_must_not_overwrite_input")
    if args.stage in ("plan-events", "register", "report-events", "audit-events"):
        result = _run_event_stage(args)
    elif args.stage == "plan":
        if args.apply or not all(
            (args.start, args.end, args.batch_id, args.cost_evidence)
        ):
            raise DailyBasicValidationError("history_plan_arguments")
        lake = Path(DEFAULT_LAKE_ROOT)
        calendar = silver_trade_calendar_path(lake)
        calendar_hash = file_sha256(calendar)
        settings = replace(
            DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=Path("/private/tmp")
        )
        with connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as connection:
            rows = connection.execute(
                f"SELECT CAST(trade_date AS VARCHAR) FROM {read_parquet(calendar, hive_partitioning=False)} "
                "WHERE exchange='SSE' AND is_open=true AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) "
                "ORDER BY trade_date",
                [args.start, args.end],
            ).fetchall()
        if (
            len({r[0] for r in rows}) != len(rows)
            or file_sha256(calendar) != calendar_hash
        ):
            raise DailyBasicValidationError("history_calendar_changed_or_duplicate")
        costs = history_cost_estimate(json.loads(args.cost_evidence.read_text()))
        costs["evidence_path"] = str(args.cost_evidence.absolute())
        costs["evidence_sha256"] = file_sha256(args.cost_evidence)
        budgets = {n: getattr(args, n) for n in LIMIT_NAMES}
        if all(v is None for v in budgets.values()):
            budgets = None
        result = make_history_plan(
            start=args.start,
            end=args.end,
            batch_id=args.batch_id,
            lake_root=lake,
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            calendar_path=calendar,
            dates=[r[0] for r in rows],
            source_evidence=DailyBasicHistorySource(ProdPostgresResource()).inspect(
                args.start, args.end
            ),
            cost_evidence=costs,
            limits=budgets,
        )
    else:
        if args.plan is None:
            raise DailyBasicValidationError("history_plan_required")
        plan = load_history_report(args.plan)
        if (
            plan["lake_root"] != DEFAULT_LAKE_ROOT
            or plan["staging_root"] != DEFAULT_LAKE_STAGING_ROOT
        ):
            raise DailyBasicValidationError("history_cli_formal_roots_only")
        if args.stage in ("export", "build", "promote"):
            if not args.apply or args.fingerprint != plan["fingerprint"]:
                raise DailyBasicValidationError(
                    "history_explicit_apply_and_fingerprint_required"
                )
            if (
                not os.path.ismount("/Volumes/datasource")
                or not Path(DEFAULT_LAKE_ROOT).is_dir()
            ):
                raise DailyBasicValidationError("history_formal_volume_unavailable")
        elif args.apply:
            raise DailyBasicValidationError("history_audit_is_readonly")
        if args.stage == "export":
            result = export_daily_basic_history(
                plan, DailyBasicHistorySource(ProdPostgresResource()), apply=True
            )
        elif args.stage == "build":
            result = build_daily_basic_history(plan, apply=True)
        elif args.stage == "audit":
            result = audit_daily_basic_history(plan)
        else:
            if args.audit_report is None:
                raise DailyBasicValidationError("history_audit_required")
            result = promote_daily_basic_history(
                plan, load_history_report(args.audit_report), apply=True
            )
    save_history_report(report, result)
    print(
        json.dumps(
            {
                "stage": args.stage,
                "report": str(report),
                "fingerprint": result.get("fingerprint"),
                "stop_reasons": result.get("stop_reasons", []),
                "execution_budget_frozen": result.get("execution_budget_frozen"),
            },
            ensure_ascii=False,
        )
    )
    return result


def _run_event_stage(args):
    from orchestrator.defs.bootstrap.daily_basic_event_instance import (
        daily_basic_event_instance,
    )
    from orchestrator.defs.bootstrap.daily_basic_events import (
        apply_daily_basic_events,
        plan_daily_basic_events,
    )

    writable = args.stage in ("register", "report-events")
    if not all((args.plan, args.audit_report, args.promote_report)):
        raise DailyBasicValidationError("history_publication_reports_required")
    if args.sample_date and args.stage != "report-events":
        raise DailyBasicValidationError("history_sample_stage")
    approved = load_history_report(args.event_plan) if args.event_plan else None
    if writable and (
        not args.apply
        or approved is None
        or args.fingerprint != approved["fingerprint"]
    ):
        raise DailyBasicValidationError("history_event_explicit_apply_required")
    if not writable and args.apply:
        raise DailyBasicValidationError("history_event_plan_is_readonly")
    plan = load_history_report(args.plan)
    if (
        plan["lake_root"] != DEFAULT_LAKE_ROOT
        or plan["staging_root"] != DEFAULT_LAKE_STAGING_ROOT
    ):
        raise DailyBasicValidationError("history_cli_formal_roots_only")
    audit = load_history_report(args.audit_report)
    promote = load_history_report(args.promote_report)
    settings = replace(
        DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=Path("/private/tmp")
    )
    with (
        _event_apply_lock() if writable else nullcontext(),
        daily_basic_event_instance(writable=writable) as instance,
        connect_configured_duckdb(
            settings, temp_policy="existing_no_spill"
        ) as connection,
    ):
        if writable:
            return apply_daily_basic_events(
                instance,
                connection,
                plan,
                audit,
                promote,
                approved,
                stage=args.stage,
                apply=True,
                sample_date=args.sample_date,
            )
        return plan_daily_basic_events(instance, connection, plan, audit, promote)


@contextmanager
def _event_apply_lock():
    # Keep the inode stable across invocations; never unlink a live lock file.
    with Path("/private/tmp/daily_basic_event_publication.lock").open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DailyBasicValidationError(
                "history_event_publication_locked"
            ) from error
        yield


def main():
    run_history_cli(history_parser().parse_args())


if __name__ == "__main__":
    main()
