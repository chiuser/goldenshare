import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import duckdb

from orchestrator.defs.assets.dc_industry_hierarchy import (
    DcIndustryHierarchyValidationError,
    audit_dc_industry_hierarchy_reference,
    load_dc_industry_hierarchy_reference,
    silver_dc_industry_hierarchy,
    write_silver_dc_industry_hierarchy_snapshot,
)
from orchestrator.defs.checks.dc_industry_hierarchy_checks import (
    silver_dc_industry_hierarchy_core_check,
)
from orchestrator.defs.catalog import (
    PartitionModel,
    get_lake_asset_catalog_entry,
)
from orchestrator.defs.jobs.dc_industry_hierarchy import (
    silver_dc_industry_hierarchy_update_job,
)
from orchestrator.defs.paths import (
    silver_dc_index_path,
    silver_dc_industry_hierarchy_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.configs import (
    build_silver_dc_industry_hierarchy_update_job_run_config,
)
from orchestrator.defs.run_contracts.metadata import SourceSystem
from orchestrator.seeds.board.eastmoney_dc_industry_hierarchy import (
    EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS,
    load_eastmoney_dc_industry_hierarchy_seed,
)


REFERENCE_TRADE_DATE = "2026-07-31"
REFERENCE_LEVEL_NAME_BY_INDUSTRY_LEVEL = {
    1: "东财一级行业",
    2: "东财二级行业",
    3: "东财三级行业",
}


def _write_reference(
    root: Path,
    *,
    missing_node_path: str | None = None,
    duplicate_first_node: bool = False,
    invalid_code: bool = False,
) -> None:
    path = silver_dc_index_path(root, REFERENCE_TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = load_eastmoney_dc_industry_hierarchy_seed()
    rows = [
        (
            "BAD" if invalid_code and index == 1 else f"BK{index:04d}.DC",
            row.name,
            "行业板块",
            REFERENCE_LEVEL_NAME_BY_INDUSTRY_LEVEL[row.industry_level],
        )
        for index, row in enumerate(seed.rows, start=1)
        if row.node_path != missing_node_path
    ]
    if duplicate_first_node:
        rows.append(("BK9999.DC", rows[0][1], "行业板块", rows[0][3]))

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE reference_rows(ts_code VARCHAR, name VARCHAR, idx_type VARCHAR, level VARCHAR)"
    )
    connection.executemany("INSERT INTO reference_rows VALUES (?, ?, ?, ?)", rows)
    connection.execute(f"COPY reference_rows TO '{path}' (FORMAT PARQUET)")
    connection.close()


class DcIndustryHierarchyAssetTests(unittest.TestCase):
    def test_asset_check_and_catalog_share_the_manual_full_snapshot_contract(self) -> None:
        entry = get_lake_asset_catalog_entry("silver_dc_industry_hierarchy")
        self.assertIsNone(silver_dc_industry_hierarchy.partitions_def)
        self.assertEqual(entry.dataset_id, "dc_industry_hierarchy")
        self.assertEqual(entry.source_system, SourceSystem.SEED)
        self.assertEqual(
            entry.partition_model,
            PartitionModel.FULL_FILE_SILVER_DC_INDUSTRY_HIERARCHY,
        )
        self.assertEqual(
            entry.blocking_check_names,
            ("silver_dc_industry_hierarchy_core_check",),
        )
        self.assertEqual(
            {spec.name for spec in silver_dc_industry_hierarchy_core_check.check_specs},
            {"silver_dc_industry_hierarchy_core_check"},
        )

    def test_writer_builds_contract_snapshot_and_core_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root)
            definitions = dg.Definitions(
                assets=[silver_dc_industry_hierarchy],
                asset_checks=[silver_dc_industry_hierarchy_core_check],
                jobs=[silver_dc_industry_hierarchy_update_job],
                resources={
                    "lake_root": LakeRootResource(root_path=str(root)),
                    "duckdb": DuckDBResource(),
                },
            )
            with patch.object(LakeRootResource, "ensure_available_for_run"):
                result = definitions.resolve_job_def(
                    "silver_dc_industry_hierarchy_update_job"
                ).execute_in_process(
                    instance=dg.DagsterInstance.ephemeral(),
                    run_config=build_silver_dc_industry_hierarchy_update_job_run_config(
                        reference_trade_date=REFERENCE_TRADE_DATE,
                    ),
                    raise_on_error=True,
                )

            target_path = silver_dc_industry_hierarchy_path(root)
            self.assertTrue(result.success)
            self.assertTrue(target_path.is_file())
            connection = duckdb.connect()
            row_count = connection.execute(
                f"SELECT count(*) FROM read_parquet('{target_path}', hive_partitioning=false)"
            ).fetchone()[0]
            level_counts = dict(
                connection.execute(
                    f"SELECT industry_level, count(*) FROM read_parquet('{target_path}', hive_partitioning=false) GROUP BY industry_level"
                ).fetchall()
            )
            column_names = [
                row[0]
                for row in connection.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{target_path}', hive_partitioning=false)"
                ).fetchall()
            ]
            connection.close()
            self.assertEqual(row_count, 496)
            self.assertEqual(level_counts, EASTMONEY_DC_INDUSTRY_HIERARCHY_LEVEL_COUNTS)
            self.assertEqual(
                column_names,
                [
                    "ts_code",
                    "name",
                    "industry_level",
                    "industry_level_name",
                    "parent_ts_code",
                    "parent_name",
                    "root_ts_code",
                    "root_name",
                    "hierarchy_path",
                    "is_leaf",
                    "display_order",
                    "baseline_version",
                    "source_received_date",
                    "code_reference_trade_date",
                ],
            )
            check_events = [
                event.event_specific_data
                for event in result.all_events
                if event.event_type == dg.DagsterEventType.ASSET_CHECK_EVALUATION
            ]
            self.assertEqual(len(check_events), 1)
            self.assertTrue(check_events[0].passed)

    def test_reference_audit_rejects_missing_seed_node_without_replacing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_node = load_eastmoney_dc_industry_hierarchy_seed().rows[-1].node_path
            _write_reference(root, missing_node_path=missing_node)
            target_path = silver_dc_industry_hierarchy_path(root)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"existing snapshot must remain")

            with self.assertRaisesRegex(DcIndustryHierarchyValidationError, "level_counts"):
                write_silver_dc_industry_hierarchy_snapshot(
                    lake_root_path=root,
                    duckdb_resource=DuckDBResource(),
                    reference_trade_date=REFERENCE_TRADE_DATE,
                )

            self.assertEqual(target_path.read_bytes(), b"existing snapshot must remain")

    def test_reference_loader_rejects_duplicate_level_name_and_invalid_bk_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root, duplicate_first_node=True)
            with self.assertRaisesRegex(DcIndustryHierarchyValidationError, "duplicate_level_name_count"):
                load_dc_industry_hierarchy_reference(
                    lake_root_path=root,
                    duckdb_resource=DuckDBResource(),
                    reference_trade_date=REFERENCE_TRADE_DATE,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root, invalid_code=True)
            with self.assertRaisesRegex(DcIndustryHierarchyValidationError, "invalid_count"):
                load_dc_industry_hierarchy_reference(
                    lake_root_path=root,
                    duckdb_resource=DuckDBResource(),
                    reference_trade_date=REFERENCE_TRADE_DATE,
                )

    def test_promote_failure_keeps_existing_snapshot_and_removes_staging_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root)
            target_path = silver_dc_industry_hierarchy_path(root)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(b"known good snapshot")
            with patch(
                "orchestrator.defs.assets.dc_industry_hierarchy.os.replace",
                side_effect=OSError("promote failed"),
            ):
                with self.assertRaisesRegex(OSError, "promote failed"):
                    write_silver_dc_industry_hierarchy_snapshot(
                        lake_root_path=root,
                        duckdb_resource=DuckDBResource(),
                        reference_trade_date=REFERENCE_TRADE_DATE,
                    )
            self.assertEqual(target_path.read_bytes(), b"known good snapshot")
            self.assertEqual(
                [path for path in target_path.parent.iterdir() if path.name.endswith(".tmp")],
                [],
            )

    def test_reference_audit_is_two_way_on_the_valid_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_reference(root)
            reference = load_dc_industry_hierarchy_reference(
                lake_root_path=root,
                duckdb_resource=DuckDBResource(),
                reference_trade_date=REFERENCE_TRADE_DATE,
            )
            audit = audit_dc_industry_hierarchy_reference(
                duckdb_resource=DuckDBResource(),
                reference=reference,
            )
            self.assertEqual(audit.missing_seed_node_count, 0)
            self.assertEqual(audit.extra_reference_node_count, 0)


if __name__ == "__main__":
    unittest.main()
