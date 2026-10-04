"""Operator date-window planner and explicit file runner; no Dagster event writes."""

import argparse
import json
import os
import uuid
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import announcement_dates
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.anns_d_source import AnnouncementProcessCall
from orchestrator.defs.anns_d_window import (
    announcement_day_run_id,
    announcement_window_tags,
    execute_announcement_window_day,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import TushareResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy


def announcement_cli_parser():
    parser = argparse.ArgumentParser(
        description="DG公告日补拉：默认plan零写入；run显式写Raw，不补报Dagster事件。"
    )
    parser.add_argument("mode", nargs="?", choices=("plan", "run"), default="plan")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--interval-seconds", type=float, default=AnnouncementPolicy().interval_seconds
    )
    parser.add_argument(
        "--window-id",
        help="运营执行身份；使用原值续跑，不改变日期或间隔。新执行默认UUID。",
    )
    return parser


def announcement_cli(argv=None):
    args = announcement_cli_parser().parse_args(argv)
    days = announcement_dates(args.start_date, args.end_date)
    policy = AnnouncementPolicy(interval_seconds=args.interval_seconds)
    window_id = args.window_id or uuid.uuid4().hex
    tags = announcement_window_tags(window_id, days[0], days[-1])
    print(
        json.dumps(
            {
                "phase": "plan",
                "window_id": window_id,
                "start_date": days[0],
                "end_date": days[-1],
                "days_total": len(days),
                "interval_seconds": policy.interval_seconds,
                "max_window_requests": policy.max_window_requests,
                "max_window_seconds": policy.max_window_seconds,
                "event_write": False,
            },
            ensure_ascii=False,
        )
    )
    if args.mode == "plan":
        return 0
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise ValueError("announcement_tushare_token_missing")
    control = AnnouncementControl(
        emit=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True)
    )
    for day in days:
        control.check()
        store = AnnouncementStore(
            Path(DEFAULT_LAKE_ROOT),
            Path(DEFAULT_LAKE_STAGING_ROOT),
            announcement_day_run_id(window_id, day),
            policy,
            control,
        )
        call = AnnouncementProcessCall(
            TushareResource(token=token).token, store.directory, policy
        )
        execute_announcement_window_day(day, call, store, control, tags)
    return 0


if __name__ == "__main__":
    raise SystemExit(announcement_cli())
