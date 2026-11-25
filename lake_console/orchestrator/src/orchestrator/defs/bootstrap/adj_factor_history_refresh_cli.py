"""Explicit prepare, publish and event registration for historical factor revisions."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.adj_factor_history_refresh import (
    FIELDS,
    PAGE_SIZE,
    prepare_history_refresh,
    publish_history_refresh,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import TushareResource
from orchestrator.defs.stock_factor_price_checks import ADJ_FACTOR_PARTITION_SET
from orchestrator.defs.tushare_api_io import iter_tushare_pages


def _source_snapshot_pages(root: Path, day: str):
    capture = json.loads((root / f"{day}.adj_factor.json").read_text(encoding="utf-8"))
    rows = capture["rows"]
    for offset, size in capture["pages"]:
        page = rows[offset:offset + size]
        if len(page) != size:
            raise ValueError(f"Invalid isolated source snapshot: {day}")
        yield offset, page


def _source_pages(client: TushareResource, day: str):
    return iter_tushare_pages(
        tushare=client, api_name="adj_factor", api_params={"trade_date": day.replace("-", "")},
        field_names=FIELDS, limit=PAGE_SIZE,
    )


def _progress(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False), flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_subparsers(dest="stage", required=True)
    for name in ("prepare", "publish", "register-events"):
        command = stage.add_parser(name)
        command.add_argument("--operation-id", required=True)
        command.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
        command.add_argument("--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT))
        if name != "register-events":
            command.add_argument("--registered-days-file", type=Path,
                                 help="Isolated test only. JSON list of registered dates.")
        if name == "prepare":
            command.add_argument("--start-date", required=True)
            command.add_argument("--end-date", required=True)
            command.add_argument("--source-snapshot-dir", type=Path, help="Isolated test only.")
        elif name == "register-events":
            command.add_argument("--event-scope", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> dict:
    parser = _parser()
    args = parser.parse_args(argv)
    common = {"lake": args.lake_root, "staging": args.staging_root, "operation_id": args.operation_id,
              "cancel": _check_stop, "progress": _progress}
    if args.stage == "register-events":
        from orchestrator.defs.bootstrap.adj_factor_history_refresh_events import (
            register_history_events,
        )

        with dg.DagsterInstance.get() as instance:
            return register_history_events(instance=instance, scope_path=args.event_scope, **common)

    formal = args.lake_root == Path(DEFAULT_LAKE_ROOT)
    source_snapshots = getattr(args, "source_snapshot_dir", None)
    if formal:
        if args.registered_days_file or source_snapshots:
            parser.error("Isolated fixtures cannot be used with formal Lake")
        with dg.DagsterInstance.get() as instance:
            registered = set(instance.get_dynamic_partitions(ADJ_FACTOR_PARTITION_SET))
    else:
        if args.registered_days_file is None or (args.stage == "prepare" and source_snapshots is None):
            parser.error("Isolated roots require fixture dates and, for prepare, source snapshots")
        registered = set(json.loads(args.registered_days_file.read_text(encoding="utf-8")))
    if args.stage == "publish":
        return publish_history_refresh(registered=registered, **common)

    if source_snapshots is not None:
        def pages(day: str):
            return _source_snapshot_pages(source_snapshots, day)
    else:
        client = TushareResource(token=os.environ["TUSHARE_TOKEN"])

        def pages(day: str):
            return _source_pages(client, day)

    return prepare_history_refresh(start=args.start_date, end=args.end_date, registered=registered,
                                   pages=pages, **common)


_stop_requested = False


def _request_stop(_signum, _frame) -> None:
    global _stop_requested
    _stop_requested = True


def _check_stop() -> None:
    if _stop_requested:
        raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    try:
        print(json.dumps(main(), ensure_ascii=False), flush=True)
    except KeyboardInterrupt:
        raise SystemExit("Interrupted. Resume with the same operation ID.") from None
