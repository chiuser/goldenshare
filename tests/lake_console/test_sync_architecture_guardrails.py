from __future__ import annotations

import ast
from pathlib import Path


def test_lake_cli_entrypoint_is_thin():
    root = Path("lake_console/backend/app/cli")
    assert (root / "__main__.py").exists()
    assert (root / "main.py").exists()
    assert (root / "commands" / "sync_dataset.py").exists()
    assert not Path("lake_console/backend/app/cli.py").exists()


def test_lake_sync_engine_uses_strategy_registry():
    content = Path("lake_console/backend/app/sync/engine.py").read_text(encoding="utf-8")
    assert "STRATEGY_CLASSES" in content
    assert 'if dataset_key == "daily"' not in content
    assert 'if dataset_key != "index_basic"' not in content


def test_lake_planner_dispatches_to_planner_modules():
    planner_content = Path("lake_console/backend/app/sync/planner.py").read_text(encoding="utf-8")
    assert "build_snapshot_plan" in planner_content
    assert "build_trade_date_plan" in planner_content
    assert "build_stk_mins_plan" in planner_content
    assert Path("lake_console/backend/app/sync/planners/snapshot.py").exists()
    assert Path("lake_console/backend/app/sync/planners/trade_date.py").exists()
    assert Path("lake_console/backend/app/sync/planners/stk_mins.py").exists()


def test_lake_sync_strategy_registry_is_explicit():
    registry = Path("lake_console/backend/app/sync/strategies/__init__.py").read_text(encoding="utf-8")
    assert "STRATEGY_CLASSES" in registry
    assert "DailyStrategy.dataset_key" in registry
    assert "IndexBasicStrategy.dataset_key" in registry


def test_lake_cli_command_modules_do_not_import_dataset_services_in_main():
    tree = ast.parse(Path("lake_console/backend/app/cli/main.py").read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
    assert all("services.tushare_" not in module for module in imported_modules)
