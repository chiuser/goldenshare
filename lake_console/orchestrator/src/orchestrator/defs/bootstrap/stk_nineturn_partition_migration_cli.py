"""CLI for guarded stock nine-turn dynamic-partition migration."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stk_nineturn_partition_migration import (
    apply_stk_nineturn_partition_migration,
    plan_stk_nineturn_partition_migration,
)
from orchestrator.defs.resources import DuckDBResource


def _default_output(*, apply: bool) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    action = "apply" if apply else "plan"
    return Path("/private/tmp") / (
        f"stk_nineturn_partition_migration_{action}_{timestamp}.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="stk_nineturn_partition_migration")
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("DAGSTER_HOME"):
        parser.error("DAGSTER_HOME must be set to the approved Dagster instance.")
    instance = dg.DagsterInstance.get()
    if args.apply:
        report = apply_stk_nineturn_partition_migration(
            instance=instance,
            lake_root=args.lake_root,
            duckdb_resource=DuckDBResource(),
            confirm_apply=True,
        ).to_dict()
    else:
        report = plan_stk_nineturn_partition_migration(
            instance=instance,
            lake_root=args.lake_root,
            duckdb_resource=DuckDBResource(),
        ).to_dict()
    output = args.output or _default_output(apply=args.apply)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
