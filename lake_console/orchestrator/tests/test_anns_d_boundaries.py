"""Negative gates: helper development must not register or mutate other systems."""

import ast
from pathlib import Path


def test_announcement_core_has_no_external_business_imports_or_database_writes():
    root = Path(__file__).parents[1] / "src/orchestrator/defs"
    files = [
        *root.glob("anns_d_*.py"),
        root / "prod_db/anns_d.py",
        *root.glob("bootstrap/anns_d_history*.py"),
        root / "run_contracts/anns_d.py",
    ]
    for file in files:
        source = file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("src.ops", "src.app", "src.foundation", "lake_console.backend")
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in (
                    "report_runless_asset_event",
                    "add_dynamic_partitions",
                )
        if file.parent.name == "prod_db":
            assert "connect_readonly_transaction" in source
            assert (
                "INSERT INTO" not in source
                and "DELETE FROM" not in source
                and "UPDATE raw_" not in source
            )
        assert "kopia " not in source and "duckdb.connect(" not in source


def test_core_helpers_do_not_create_dagster_definitions():
    root = Path(__file__).parents[1] / "src/orchestrator/defs"
    for path in [*root.glob("anns_d_*.py"), *root.glob("bootstrap/anns_d_history*.py")]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in (
                    "asset",
                    "asset_check",
                    "ScheduleDefinition",
                    "define_asset_job",
                )
