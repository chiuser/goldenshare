"""受控指数周月线初始化入口；默认仅显示范围，不连接外部资源。"""

import argparse
import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.index_period_history import (
    bootstrap_index_period_history,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    index_period_candidate_path,
)
from orchestrator.defs.prod_db.index_period import prod_index_period_query
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
)
from orchestrator.defs.run_contracts.index_period import INDEX_MONTHLY, INDEX_WEEKLY


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        index_period_candidate_path(
            Path(DEFAULT_LAKE_STAGING_ROOT), args.operation_id, "raw", "index_weekly"
        )
    except ValueError as error:
        parser.error(str(error))
    if not args.apply:
        print(
            json.dumps(
                {
                    "apply": False,
                    "lake_root": DEFAULT_LAKE_ROOT,
                    "staging_root": DEFAULT_LAKE_STAGING_ROOT,
                    "queries": [
                        prod_index_period_query(p, layer)
                        for p in (INDEX_WEEKLY, INDEX_MONTHLY)
                        for layer in ("raw", "serving")
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    root = LakeRootResource()
    root.ensure_available_for_run()
    with dg.DagsterInstance.get() as instance:
        result = bootstrap_index_period_history(
            duckdb=DuckDBResource(),
            prod_postgres=ProdPostgresResource(),
            lake_root=root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            operation_id=args.operation_id,
            instance=instance,
            log=print,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
