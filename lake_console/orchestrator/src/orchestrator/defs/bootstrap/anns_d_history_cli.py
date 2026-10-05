"""Announcement history CLI: plan, capture, build, audit and promote separately."""

import argparse
import json
import signal
import threading
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    announcement_history_run_id,
    run_announcement_history_stage,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    announcement_bootstrap_volume_gate,
    load_announcement_history_document,
    make_announcement_history_plan,
    save_announcement_history_report,
    seal_history_document,
    validate_announcement_history_plan,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.prod_db.anns_d import AnnouncementHistorySource
from orchestrator.defs.resources import ProdPostgresResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy


def announcement_history_parser():
    parser = argparse.ArgumentParser(
        description="DG公告历史bootstrap；默认plan，只读来源，文件与事件阶段分离。"
    )
    parser.add_argument(
        "stage",
        nargs="?",
        default="plan",
        choices=("plan", "capture", "build", "audit", "promote", "status"),
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--run-id")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--fingerprint")
    parser.add_argument(
        "--month", help="计划中某个完整自然月，使用YYYY-MM-01；省略则选择计划全部月份。"
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument(
        "--formal", action="store_true", help="audit仅核验正式文件；不能用于其它阶段。"
    )
    return parser


def _history_cli_arguments(args):
    if args.formal and args.stage != "audit":
        raise AnnouncementError("announcement_formal_audit_only")
    if args.stage == "plan":
        announcement_bootstrap_volume_gate(DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT)
        if not all((args.start_date, args.end_date, args.run_id, args.report)) or any(
            (args.plan, args.fingerprint, args.month, args.audit_report)
        ):
            raise AnnouncementError("announcement_plan_arguments")
    elif any((args.start_date, args.end_date, args.run_id)) or not args.plan:
        raise AnnouncementError("announcement_stage_requires_frozen_plan")
    if args.stage in ("capture", "build", "promote") and not args.fingerprint:
        raise AnnouncementError("announcement_explicit_plan_fingerprint_required")
    if args.stage == "promote" and not args.audit_report:
        raise AnnouncementError("announcement_history_green_audit_required")
    if args.stage != "promote" and args.audit_report:
        raise AnnouncementError("announcement_audit_report_promote_only")
    if args.stage == "audit" and not args.report:
        raise AnnouncementError("announcement_audit_report_required")
    if args.report:
        path = assert_safe_announcement_path(args.report)
        if Path("/private/tmp") not in path.parents or path.exists():
            raise AnnouncementError("announcement_new_private_tmp_report_required")


def execute_announcement_history_cli(args, control):
    _history_cli_arguments(args)
    if args.stage == "plan":
        policy = AnnouncementPolicy()
        inventory = AnnouncementHistorySource(ProdPostgresResource(), policy).inventory(
            args.start_date, args.end_date, control
        )
        plan = make_announcement_history_plan(
            args.start_date, args.end_date, args.run_id, inventory, policy
        )
        save_announcement_history_report(args.report, plan)
        return {
            "plan": str(args.report),
            "fingerprint": plan["fingerprint"],
            **plan["cost"],
        }
    plan = load_announcement_history_document(
        args.plan, kind="anns_d_history_plan", fingerprint=args.fingerprint
    )
    validate_announcement_history_plan(plan)
    months = [
        month
        for month in plan["months"]
        if not args.month or month["month"] == args.month
    ]
    if not months:
        raise AnnouncementError("announcement_month_not_planned")
    audit_bundle = None
    if args.stage == "promote":
        audit_bundle = load_announcement_history_document(
            args.audit_report, kind="anns_d_history_audit_bundle"
        )
        if audit_bundle["plan_fingerprint"] != plan["fingerprint"]:
            raise AnnouncementError("announcement_history_green_audit_required")
    source = (
        AnnouncementHistorySource(
            ProdPostgresResource(), AnnouncementPolicy(**plan["policy"])
        )
        if args.stage == "capture"
        else None
    )
    results = []
    for month in months:
        control.check()
        if args.stage == "status":
            path = (
                Path(plan["staging_root"])
                / "anns_d"
                / f"run_id={announcement_history_run_id(plan, month)}"
                / "capture.json"
            )
            assert_safe_announcement_path(path)
            document = AnnouncementCheckpoint(
                path, {"plan_fingerprint": plan["fingerprint"], "month": month["month"]}
            ).document
            results.append(
                {
                    "month": month["month"],
                    "phase": document["phase"],
                    "source_rows": document.get("source_rows", 0),
                }
            )
        else:
            audit = (
                next(
                    (
                        row
                        for row in audit_bundle["months"]
                        if row["month"] == month["month"]
                    ),
                    None,
                )
                if audit_bundle
                else None
            )
            results.append(
                run_announcement_history_stage(
                    args.stage,
                    plan,
                    month,
                    control,
                    source=source,
                    audit=audit,
                    formal=args.formal,
                )
            )
    report = seal_history_document(
        {
            "kind": "anns_d_history_audit_bundle"
            if args.stage == "audit"
            else "anns_d_history_stage_report",
            "stage": args.stage,
            "plan_fingerprint": plan["fingerprint"],
            "months": results,
            "event_writes": 0,
        }
    )
    if args.report:
        save_announcement_history_report(args.report, report)
    return report


def announcement_history_cli(argv=None):
    args = announcement_history_parser().parse_args(argv)
    cancellation = threading.Event()

    def request_cancel(_signum, _frame):
        cancellation.set()

    previous = {
        number: signal.signal(number, request_cancel)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        control = AnnouncementControl(
            cancelled=cancellation.is_set,
            emit=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True),
        )
        result = execute_announcement_history_cli(args, control)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    raise SystemExit(announcement_history_cli())
