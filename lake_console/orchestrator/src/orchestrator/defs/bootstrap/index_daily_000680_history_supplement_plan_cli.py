"""CLI for the read-only 000680.SH history-supplement planner."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dagster import DagsterInstance

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    DEFAULT_STAGING_ROOT,
    IndexDaily000680HistorySupplementPlanError,
    run_dry_run,
    write_report,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only 000680.SH history-supplement planner."
    )
    parser.add_argument(
        "--lake-root", type=Path, default=Path("/Volumes/datasource/data_lake")
    )
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or Path(
        "/private/tmp/"
        + "index_daily_000680_history_supplement_plan_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    try:
        with DagsterInstance.get() as instance:
            plan = run_dry_run(
                lake_root=args.lake_root,
                staging_root=args.staging_root,
                duckdb_resource=DuckDBResource(),
                prod_postgres=ProdPostgresResource(),
                instance=instance,
                run_id=args.run_id,
            )
        write_report(plan, output)
    except (
        IndexDaily000680HistorySupplementPlanError,
        RuntimeError,
        OSError,
        ValueError,
    ) as error:
        print(f"000680.SH supplement plan stopped: {error}", file=sys.stderr)
        return 2
    print(output)
    print(f"plan_hash={plan.plan_hash}")
    print(f"should_stop={plan.should_stop}")
    return 3 if plan.should_stop else 0


if __name__ == "__main__":
    raise SystemExit(main())
