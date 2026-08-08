"""CLI for 000680.SH partition and runless materialization reconciliation."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dagster import DagsterInstance

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_apply import (
    IndexDaily000680HistorySupplementApplyError,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_events import (
    IndexDaily000680HistorySupplementEventsError,
    plan_supplement_events,
    report_supplement_events,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or explicitly apply 000680.SH Dagster reconciliation."
    )
    parser.add_argument("stage", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--physical-audit", type=Path, required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-partition-write", action="store_true")
    parser.add_argument("--confirm-event-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or Path(
        "/private/tmp/index_daily_000680_history_supplement_events_"
        + args.stage
        + "_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    try:
        with DagsterInstance.get() as instance:
            if args.stage == "plan":
                report = plan_supplement_events(
                    instance=instance,
                    plan_path=args.plan,
                    physical_audit_path=args.physical_audit,
                    expected_plan_hash=args.expected_plan_hash,
                )
            else:
                report = report_supplement_events(
                    instance=instance,
                    plan_path=args.plan,
                    physical_audit_path=args.physical_audit,
                    expected_plan_hash=args.expected_plan_hash,
                    apply=args.apply,
                    confirm_partition_write=args.confirm_partition_write,
                    confirm_event_write=args.confirm_event_write,
                )
        write_report(report, output)
    except (
        IndexDaily000680HistorySupplementApplyError,
        IndexDaily000680HistorySupplementEventsError,
        OSError,
        RuntimeError,
    ) as error:
        print(f"000680.SH event reconciliation stopped: {error}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
