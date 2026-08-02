import tempfile
import unittest
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.assets.dc_industry_hierarchy import (
    silver_dc_industry_hierarchy,
    write_silver_dc_industry_hierarchy_snapshot,
)
from orchestrator.defs.checks.dc_industry_hierarchy_checks import (
    silver_dc_industry_hierarchy_core_check,
)
from orchestrator.defs.paths import (
    silver_dc_index_path,
    silver_dc_industry_hierarchy_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.seeds.board.eastmoney_dc_industry_hierarchy import (
    load_eastmoney_dc_industry_hierarchy_seed,
)


REFERENCE_TRADE_DATE = "2026-07-31"
REFERENCE_LEVEL_NAME_BY_INDUSTRY_LEVEL = {
    1: "东财一级行业",
    2: "东财二级行业",
    3: "东财三级行业",
}


def _write_reference(root: Path) -> None:
    path = silver_dc_index_path(root, REFERENCE_TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            f"BK{index:04d}.DC",
            row.name,
            "行业板块",
            REFERENCE_LEVEL_NAME_BY_INDUSTRY_LEVEL[row.industry_level],
        )
        for index, row in enumerate(
            load_eastmoney_dc_industry_hierarchy_seed().rows,
            start=1,
        )
    ]
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE reference_rows(ts_code VARCHAR, name VARCHAR, idx_type VARCHAR, level VARCHAR)"
    )
    connection.executemany("INSERT INTO reference_rows VALUES (?, ?, ?, ?)", rows)
    connection.execute(f"COPY reference_rows TO '{path}' (FORMAT PARQUET)")
    connection.close()


def _report_reference_materialization(instance: dg.DagsterInstance, root: Path) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=silver_dc_industry_hierarchy.key,
            metadata={
                "goldenshare/code_reference_trade_date": REFERENCE_TRADE_DATE,
                "goldenshare/code_reference_file_path": str(
                    silver_dc_index_path(root, REFERENCE_TRADE_DATE)
                ),
            },
        )
    )


class DcIndustryHierarchyCheckTests(unittest.TestCase):
    def test_missing_file_and_materialization_metadata_fail_with_compact_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            instance = dg.DagsterInstance.ephemeral()
            context = dg.build_asset_check_context(instance=instance)
            result = silver_dc_industry_hierarchy_core_check(
                context,
                LakeRootResource(root_path=temp_dir),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)
            self.assertEqual(
                result.metadata["goldenshare/failed_rule_names"].value,
                ["file_exists", "materialization_reference_metadata"],
            )
            self.assertLessEqual(
                len(result.metadata["goldenshare/failure_samples"].value), 20
            )

    def test_valid_snapshot_and_matching_materialization_reference_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root)
            write_silver_dc_industry_hierarchy_snapshot(
                lake_root_path=root,
                duckdb_resource=DuckDBResource(),
                reference_trade_date=REFERENCE_TRADE_DATE,
            )
            instance = dg.DagsterInstance.ephemeral()
            _report_reference_materialization(instance, root)
            context = dg.build_asset_check_context(instance=instance)
            result = silver_dc_industry_hierarchy_core_check(
                context,
                LakeRootResource(root_path=temp_dir),
                DuckDBResource(),
            )

            self.assertTrue(result.passed)
            self.assertEqual(result.metadata["goldenshare/failed_rule_names"].value, [])

    def test_corrupt_snapshot_schema_fails_without_recomputing_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root)
            target_path = silver_dc_industry_hierarchy_path(root)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect()
            connection.execute(
                f"COPY (SELECT 'bad' AS ts_code) TO '{target_path}' (FORMAT PARQUET)"
            )
            connection.close()
            instance = dg.DagsterInstance.ephemeral()
            _report_reference_materialization(instance, root)
            context = dg.build_asset_check_context(instance=instance)
            result = silver_dc_industry_hierarchy_core_check(
                context,
                LakeRootResource(root_path=temp_dir),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)
            self.assertIn(
                "snapshot_contract",
                result.metadata["goldenshare/failed_rule_names"].value,
            )


if __name__ == "__main__":
    unittest.main()
