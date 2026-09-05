from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from src.ops.action_catalog import get_maintenance_action
from src.ops.catalog.biz_dataset_definitions import (
    get_biz_dataset_definition,
    lint_biz_dataset_definitions,
    list_biz_dataset_definitions,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITION_PATH = REPO_ROOT / "src/ops/catalog/biz_dataset_definitions.py"
LEGACY_CATALOG_PATH = REPO_ROOT / "src/ops/catalog/biz_table_catalog.py"

EXPECTED_KEYS = {
    "wealth_market_turnover_snapshot",
    "equity_daily_snapshot",
    "wealth_sector_hierarchy",
    "wealth_sector_heat_daily",
    "wealth_sector_momentum_daily",
    "wealth_sector_dual_momentum_daily",
    "wealth_sector_relative_rotation_daily",
    "wealth_sector_member_breadth_daily",
    "wealth_sector_member_ma_breadth_daily",
    "wealth_sector_price_volume_daily",
    "wealth_sector_daily_insight_summary",
    "wealth_sector_daily_insight_item",
    "news_stock_link",
    "equity_qfq_nineturn_daily",
    "index_nineturn_daily",
}
EXPECTED_GROUPS = {
    "data_mart": "数据集市",
    "sector_analysis": "板块分析",
    "content_relation": "内容关联",
    "technical_indicators": "技术指标",
}


def test_biz_dataset_definitions_are_complete_and_valid() -> None:
    definitions = list_biz_dataset_definitions()

    assert len(definitions) == 15
    assert {item.dataset_key for item in definitions} == EXPECTED_KEYS
    assert len({item.table_name for item in definitions}) == 15
    assert {item.group_key: item.group_label for item in definitions} == EXPECTED_GROUPS
    assert "core_serving.wealth_sector_analysis_publish_batch" not in {
        item.table_name for item in definitions
    }
    assert lint_biz_dataset_definitions() == ()


def test_biz_dataset_definitions_bind_maintenance_actions_to_target_tables() -> None:
    maintenance_definitions = [
        item for item in list_biz_dataset_definitions() if item.producer_type == "maintenance_action"
    ]

    assert len(maintenance_definitions) == 11
    for definition in maintenance_definitions:
        action = get_maintenance_action(definition.producer_key)
        assert action is not None
        assert action.manual_enabled is True
        assert definition.table_name in action.target_tables


def test_biz_dataset_definition_linter_rejects_invalid_contracts() -> None:
    baseline = get_biz_dataset_definition("wealth_sector_heat_daily")
    invalid = (
        replace(baseline, table_name="invalid-table"),
        replace(baseline, dataset_key="duplicate", table_name="core_serving.first"),
        replace(baseline, dataset_key="duplicate", table_name="core_serving.second"),
        replace(
            baseline,
            dataset_key="bad_task_trace",
            table_name="core_serving.bad_task_trace",
            observation_query_key="maintenance_task_trace",
            freshness_policy_key="maintenance_task_trace",
        ),
        replace(
            baseline,
            dataset_key="visible_control",
            table_name="core_serving.wealth_sector_analysis_publish_batch",
        ),
    )

    codes = {issue.code for issue in lint_biz_dataset_definitions(invalid)}
    assert "invalid_table_name" in codes
    assert "duplicate_dataset_key" in codes
    assert "invalid_task_trace_columns" in codes
    assert "control_table_visible" in codes


def test_biz_dataset_registry_does_not_import_dagster_and_legacy_catalog_is_removed() -> None:
    tree = ast.parse(DEFINITION_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(not module.startswith("lake_console") for module in imported_modules)
    assert not LEGACY_CATALOG_PATH.exists()
