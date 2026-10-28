"""Archive of the executed minimal missing-asof reproduction.

Run from /Users/congming/github/goldenshare/lake_console/orchestrator:
  env -u DAGSTER_HOME -u TUSHARE_TOKEN .venv/bin/python3 -B \
    /private/tmp/dg-period-independent-audit-20261028/silver_missing_asof.py

Uses six small temporary Parquet files from the existing literal producer fixture
and owned ephemeral Dagster instances. No formal Lake, instance, source or network
access. TemporaryDirectory removes all generated fixture files when finished.
Only the current materialization's goldenshare/silver_asof is deliberately removed.
"""

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import dagster as dg

from tests.test_stock_period_silver_contracts import period_fixture
from tests.test_stock_period_silver_execution import execute
from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
    batch_event_evidence,
    require_checks,
)
from orchestrator.defs.run_contracts.stock_period_silver import asset_name


results = []
with TemporaryDirectory(prefix="dg-period-audit-metadata-", dir="/private/tmp") as d:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        f = period_fixture.__wrapped__(Path(d))
        execute(f)
        execution = silver.load_execution(f["lake"], f["staging"], f["run_id"])
        identity = execution["identity"]
        for freq in ("week", "month"):
            unit = next(u for u in identity["units"] if u["freq"] == freq)
            item = silver.read_json(
                silver.checkpoint_path(
                    silver.run_directory(f["staging"], f["run_id"]), unit
                )
            )
            metadata = silver.materialization_metadata(item, identity)
            del metadata["goldenshare/silver_asof"]
            with dg.DagsterInstance.ephemeral() as instance:
                asset = dg.AssetKey(asset_name(freq))
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=asset, partition=item["period"], metadata=metadata
                    )
                )
                event_filter = dg.AssetRecordsFilter(
                    asset_key=asset, asset_partitions=[item["period"]]
                )
                before = instance.fetch_materializations(event_filter, limit=10).records
                cli.run_reporting(
                    instance, lambda ctx: cli.report_file(instance, ctx, item, identity)
                )
                current = batch_event_evidence(
                    instance, freq, [item["period"]], include_raw=False
                )[(asset.to_user_string(), item["period"])]
                accepted = require_checks(current, freq, raw=False)
                try:
                    checks.evaluate(
                        SimpleNamespace(instance=instance, partition_key=item["period"]),
                        f["lake"], f["staging"], freq, "file_contract",
                    )
                    native_error = None
                except ValueError as error:
                    native_error = str(error)
                after = instance.fetch_materializations(event_filter, limit=10).records
                results.append(
                    {
                        "freq": freq,
                        "rows": item["rows"],
                        "version_same": before[0].storage_id == after[0].storage_id,
                        "new_materializations": len(after) - len(before),
                        "checks_after": len(current["checks"]),
                        "all_passed": all(
                            c.evaluation.passed and c.evaluation.blocking
                            for c in current["checks"].values()
                        ),
                        "require_checks_accepted": accepted.storage_id,
                        "native_check_error": native_error,
                        "silver_asof_after": getattr(
                            after[0].asset_materialization.metadata.get(
                                "goldenshare/silver_asof"
                            ), "value", None,
                        ),
                    }
                )
print(
    json.dumps(
        {
            "dagster_version": dg.__version__,
            "cases": results,
            "temp_removed": not Path(d).exists(),
        },
        ensure_ascii=False,
    )
)
