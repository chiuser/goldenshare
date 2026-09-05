"""Protect current history/recovery while preventing retired adapters returning."""

import ast
import importlib.util
from pathlib import Path

import pytest

from orchestrator.defs import duckdb_sql
from orchestrator.defs.catalog.lake_assets import (
    IngestionSource,
    list_lake_asset_catalog_entries,
)
from orchestrator.defs.run_contracts.metadata import SourceSystem

RETIRED_MODULES = (
    "source_method",
    "dataset_spec",
    "old_lake_executor",
    "specs",
    "adj_factor_raw_bootstrap_events",
    "adj_factor_silver_bootstrap_events",
)
RETIRED_TEMPLATES = (
    "TRADE_CALENDAR",
    "STOCK_BASIC",
    "STOCK_DAILY",
    "STK_MINS",
    "STOCK_IDENTITY_MAP",
    "ADJ_FACTOR",
    "SUSPEND_D",
)


@pytest.mark.parametrize("name", RETIRED_MODULES)
def test_retired_module_has_no_runtime_source(name):
    spec = importlib.util.find_spec(f"orchestrator.defs.bootstrap.{name}")
    if name == "specs":
        # An ignored __pycache__ may leave a namespace directory locally.
        # Do not delete ignored files just to make the directory disappear.
        assert spec is None or spec.origin is None
        if spec is not None:
            for dataset in (
                "adj_factor",
                "stk_mins",
                "stock_basic",
                "stock_daily",
                "stock_identity_map",
                "suspend_d",
                "trade_calendar",
            ):
                assert (
                    importlib.util.find_spec(
                        f"orchestrator.defs.bootstrap.specs.{dataset}"
                    )
                    is None
                )
    else:
        assert spec is None


def test_formal_code_has_no_retired_imports_or_source_values():
    root = Path(__file__).resolve().parents[1] / "src/orchestrator"
    forbidden = tuple(f"orchestrator.defs.bootstrap.{name}" for name in RETIRED_MODULES)
    issues = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                forbidden
            ):
                issues.append((path, node.lineno))
            if isinstance(node, ast.Import):
                issues.extend(
                    (path, node.lineno)
                    for alias in node.names
                    if alias.name.startswith(forbidden)
                )
            if isinstance(node, ast.Attribute) and node.attr == "OLD_LAKE_BOOTSTRAP":
                issues.append((path, node.lineno))
    assert issues == []
    assert "OLD_LAKE_BOOTSTRAP" not in SourceSystem.__members__
    assert "OLD_LAKE_BOOTSTRAP" not in IngestionSource.__members__
    assert all(
        not hasattr(duckdb_sql, f"{name}_BOOTSTRAP_SELECT_TEMPLATE")
        for name in RETIRED_TEMPLATES
    )


def test_exact_seventeen_catalog_entries_keep_current_sources():
    entries = {entry.asset_key: entry for entry in list_lake_asset_catalog_entries()}
    expected = {"silver_adj_factor", "silver_index_daily"}
    for freq in (1, 5, 15, 30, 60):
        raw = entries[f"raw_stk_mins_{freq}m"]
        assert raw.ingestion_sources == (
            IngestionSource.TUSHARE_API,
            IngestionSource.PROD_DB_READONLY,
        )
        assert raw.default_daily_ingestion_source == IngestionSource.PROD_DB_READONLY
        assert raw.bootstrap_sources == (IngestionSource.PROD_DB_READONLY,)
        expected.update((f"silver_stk_mins_{freq}m", f"gold_stk_mins_qfq_{freq}m"))
    for name in expected:
        assert entries[name].bootstrap_sources == (IngestionSource.DERIVED_FROM_ASSETS,)
    assert len(expected) + 5 == 17


@pytest.mark.parametrize(
    "name",
    (
        "adj_factor_silver_history",
        "stk_mins_raw_replace_from_prod",
        "stk_mins_raw_replace_from_prod_cli",
        "stk_mins_silver_history_cli",
        "stk_mins_qfq_history_cli",
        "stk_mins_qfq_derived_history_cli",
        "stk_mins_qfq_macd_kdj_history_cli",
        "cn_a_minute_gold_history",
    ),
)
def test_current_history_and_recovery_modules_remain(name):
    assert importlib.util.find_spec(f"orchestrator.defs.bootstrap.{name}") is not None


def test_recovery_has_no_backup_or_active_event_entry():
    root = Path(__file__).resolve().parents[1] / "src/orchestrator/defs/bootstrap"
    source = (root / "stk_mins_raw_replace_from_prod.py").read_text()
    assert all(
        token not in source
        for token in (
            "_quarantine",
            "_backup_path",
            "_restore_backups",
            "shutil.rmtree",
            "report_runless_asset_event",
            "@dg.asset",
            "@dg.sensor",
        )
    )
