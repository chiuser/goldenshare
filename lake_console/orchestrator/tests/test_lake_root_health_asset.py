import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.assets import lake_root_health as asset_module
from orchestrator.defs.checks import lake_root_health_checks as checks
from orchestrator.defs.health import lake_root as health
from orchestrator.defs.health.lake_root import GIB
from orchestrator.defs.health.lake_root import evaluate_lake_root_health
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.metadata import DAGSTER_COLUMN_SCHEMA_METADATA_KEY


class _DiskUsage:
    def __init__(self, free: int) -> None:
        self.free = free


class _FakeLakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root


def _make_root(base: Path) -> Path:
    root = base / "data_lake"
    for part in ("raw", "silver", "gold"):
        (root / part).mkdir(parents=True, exist_ok=True)
    return root


def _check_fn(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


class LakeRootHealthHelperTests(unittest.TestCase):
    def test_healthy_root_creates_tmp_and_cleans_canary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            status = evaluate_lake_root_health(
                lake_root=root,
                duckdb_temp_directory=temp,
            )

            self.assertTrue(status.healthy)
            self.assertTrue((root / "_tmp" / "lake_root_health").is_dir())
            self.assertEqual(
                list((root / "_tmp" / "lake_root_health").glob("canary-*.txt")),
                [],
            )
            self.assertEqual(list(temp.glob("canary-*.txt")), [])

    def test_required_path_missing_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            (root / "raw").rmdir()

            status = evaluate_lake_root_health(
                lake_root=root,
                duckdb_temp_directory=base / "duckdb_tmp",
            )

            self.assertFalse(status.required_paths_ready)
            self.assertIn(root / "raw", status.missing_required_paths)
            self.assertIn("required_paths_not_ready", status.failure_reasons)

    def test_required_path_non_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            (root / "raw").rmdir()
            (root / "raw").write_text("not a directory", encoding="utf-8")

            status = evaluate_lake_root_health(
                lake_root=root,
                duckdb_temp_directory=base / "duckdb_tmp",
            )

            self.assertFalse(status.required_paths_ready)
            self.assertIn(root / "raw", status.non_directory_required_paths)

    def test_canary_write_read_or_delete_failure_fails_closed(self) -> None:
        cases = (
            ("_write_canary_file", OSError("write denied")),
            ("_read_canary_file", OSError("read denied")),
            ("_delete_canary_file", OSError("delete denied")),
        )
        for function_name, error in cases:
            with self.subTest(function_name=function_name):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    root = _make_root(base)
                    with patch.object(health, function_name, side_effect=error):
                        status = evaluate_lake_root_health(
                            lake_root=root,
                            duckdb_temp_directory=base / "duckdb_tmp",
                        )

                    self.assertFalse(status.healthy)
                    self.assertFalse(status.lake_root_read_write_ready)
                    self.assertIn("lake_root_read_write_not_ready", status.failure_reasons)

    def test_lake_root_low_free_space_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            with patch.object(health.shutil, "disk_usage", return_value=_DiskUsage(1)):
                status = evaluate_lake_root_health(
                    lake_root=root,
                    duckdb_temp_directory=temp,
                )

            self.assertFalse(status.lake_root_disk_space_ready)
            self.assertIn(
                "lake_root_disk_space_below_threshold",
                status.failure_reasons,
            )

    def test_duckdb_temp_low_free_space_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            def fake_usage(path: Path) -> _DiskUsage:
                return _DiskUsage(1 if Path(path) == temp else 128 * GIB)

            with patch.object(health.shutil, "disk_usage", side_effect=fake_usage):
                status = evaluate_lake_root_health(
                    lake_root=root,
                    duckdb_temp_directory=temp,
                )

            self.assertFalse(status.duckdb_temp_directory_ready)
            self.assertIn("duckdb_temp_directory_not_ready", status.failure_reasons)

    def test_ensure_available_for_run_uses_health_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_root(Path(tmp))
            resource = LakeRootResource(root_path=str(root))

            with patch(
                "orchestrator.defs.resources.assert_lake_root_available_for_run"
            ) as guard:
                resource.ensure_available_for_run()

            guard.assert_called_once_with(root)


class LakeRootHealthDagsterDefinitionTests(unittest.TestCase):
    def test_lake_root_health_asset_materializes_metadata_without_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            with patch.object(asset_module, "DEFAULT_DUCKDB_TEMP_DIRECTORY", temp):
                result = asset_module.lake_root_health.op.compute_fn.decorated_fn(
                    _FakeLakeRoot(root)
                )

            self.assertIsInstance(result, dg.MaterializeResult)
            self.assertEqual(list(root.rglob("*.parquet")), [])
            spec = asset_module.lake_root_health.get_asset_spec()
            self.assertNotIn(DAGSTER_COLUMN_SCHEMA_METADATA_KEY, spec.metadata)

    def test_lake_root_health_asset_fails_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            with patch.object(asset_module, "DEFAULT_DUCKDB_TEMP_DIRECTORY", temp):
                with patch.object(
                    health.shutil,
                    "disk_usage",
                    return_value=_DiskUsage(1),
                ):
                    with self.assertRaises(dg.Failure) as error:
                        asset_module.lake_root_health.op.compute_fn.decorated_fn(
                            _FakeLakeRoot(root)
                        )

            self.assertIn("Lake root health check failed", str(error.exception))
            self.assertIn("failure_reasons", error.exception.metadata)

    def test_health_checks_report_expected_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = _make_root(base)
            temp = base / "duckdb_tmp"

            with patch.object(checks, "DEFAULT_DUCKDB_TEMP_DIRECTORY", temp):
                result = _check_fn(checks.lake_root_health_ready)(
                    LakeRootResource(root_path=str(root))
                )

            self.assertTrue(result.passed)
            self.assertEqual(
                checks.lake_root_health_ready.node_def.name,
                "lake_root_health_lake_root_health_ready",
            )
            self.assertEqual(
                result.metadata["goldenshare/failed_rule_names"].value,
                [],
            )
            self.assertEqual(
                result.metadata["goldenshare/rule_passed"].value,
                {
                    "lake_root_required_paths_ready": True,
                    "lake_root_read_write_ready": True,
                    "lake_root_disk_space_ready": True,
                    "duckdb_temp_directory_ready": True,
                },
            )
