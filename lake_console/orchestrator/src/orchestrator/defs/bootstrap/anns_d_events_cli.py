"""Operator event reconciliation; readonly plan, explicit frozen apply."""

import argparse
import json
import signal
import threading
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementControl,
    announcement_file_fingerprint,
    assert_safe_announcement_path,
)
from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap.anns_d_event_files import read_announcement_event_files
from orchestrator.defs.bootstrap.anns_d_event_instance import (
    INSTANCE_HOME,
    _configuration,
    open_announcement_event_instance,
)
from orchestrator.defs.bootstrap.anns_d_event_state import freeze_announcement_events
from orchestrator.defs.bootstrap.anns_d_events import (
    apply_announcement_events,
    validate_announcement_event_plan,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    load_announcement_history_document,
    save_announcement_history_report,
    seal_history_document,
)


def announcement_events_parser():
    parser = argparse.ArgumentParser(
        description="公告事件登记；默认plan，不请求源、不写业务文件。"
    )
    parser.add_argument(
        "stage",
        nargs="?",
        default="plan",
        choices=("plan", "materializations", "checks", "audit"),
    )
    parser.add_argument("--history-plan", type=Path)
    parser.add_argument("--history-audit", type=Path)
    parser.add_argument(
        "--delivery-manifest",
        type=Path,
        help="最多7个已完成delivery.json绝对路径的JSON数组。",
    )
    parser.add_argument("--event-plan", type=Path)
    parser.add_argument("--fingerprint")
    parser.add_argument("--month", help="仅执行计划内自然月YYYY-MM-01。")
    parser.add_argument("--report", type=Path, required=True)
    return parser


def execute_announcement_events_cli(args, control):
    report = assert_safe_announcement_path(args.report)
    if Path("/private/tmp") not in report.parents or report.exists():
        raise AnnouncementError("announcement_new_private_tmp_report_required")
    if args.stage == "plan":
        if args.event_plan or args.fingerprint or args.month:
            raise AnnouncementError("announcement_event_plan_arguments")
        if args.history_plan and args.history_audit and not args.delivery_manifest:
            history = load_announcement_history_document(
                args.history_plan, kind="anns_d_history_plan"
            )
            audit = load_announcement_history_document(
                args.history_audit, kind="anns_d_history_audit_bundle"
            )
            source = {
                "mode": "history",
                "history_plan": str(args.history_plan),
                "history_fingerprint": history["fingerprint"],
                "history_audit": str(args.history_audit),
                "audit_fingerprint": audit["fingerprint"],
            }
        elif args.delivery_manifest and not (args.history_plan or args.history_audit):
            source = {
                "mode": "daily",
                "delivery_manifest": str(args.delivery_manifest),
                "manifest_file": announcement_file_fingerprint(args.delivery_manifest),
            }
        else:
            raise AnnouncementError("announcement_event_source_required")
        entries = read_announcement_event_files(source, control)
        with open_announcement_event_instance() as (instance, identity):
            result = seal_history_document(
                {
                    **freeze_announcement_events(instance, entries, identity, control),
                    "source": source,
                }
            )
    else:
        if (
            any((args.history_plan, args.history_audit, args.delivery_manifest))
            or not args.event_plan
            or not args.fingerprint
        ):
            raise AnnouncementError("announcement_event_frozen_plan_required")
        plan = load_announcement_history_document(
            args.event_plan, kind="anns_d_event_plan", fingerprint=args.fingerprint
        )
        validate_announcement_event_plan(plan)
        with open_announcement_event_instance(
            identity=plan["instance_identity"], writable=args.stage != "audit"
        ) as (instance, _):
            result = seal_history_document(
                apply_announcement_events(
                    instance,
                    plan,
                    args.stage,
                    control,
                    month=args.month,
                    identity_probe=lambda: _configuration(INSTANCE_HOME)[2],
                )
            )
    save_announcement_history_report(report, result)
    return {
        "report": str(report),
        "fingerprint": result["fingerprint"],
        **result.get("counts", {}),
        **{
            k: result[k]
            for k in ("stage", "written", "records_returned")
            if k in result
        },
    }


def main(argv=None):
    args = announcement_events_parser().parse_args(argv)
    cancelled = threading.Event()
    previous = {
        sig: signal.signal(sig, lambda *_: cancelled.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    control = AnnouncementControl(
        cancelled=cancelled.is_set,
        emit=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True),
    )
    try:
        print(
            json.dumps(
                execute_announcement_events_cli(args, control), ensure_ascii=False
            ),
            flush=True,
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
