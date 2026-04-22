from __future__ import annotations

import ast
from pathlib import Path

from src.foundation.services.sync_v2.registry_parts.assemble import (
    DOMAIN_CONTRACT_GROUPS,
    SYNC_V2_CONTRACTS,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PARTS_ROOT = REPO_ROOT / "src/foundation/services/sync_v2/registry_parts"
CONTRACTS_ROOT = REGISTRY_PARTS_ROOT / "contracts"

EXPECTED_DOMAIN_FILES = {
    "market_equity",
    "market_fund",
    "index_series",
    "board_hotspot",
    "moneyflow",
    "reference_master",
    "low_frequency",
}

EXPECTED_DOMAIN_KEYS: dict[str, set[str]] = {
    "market_equity": {
        "daily",
        "adj_factor",
        "daily_basic",
        "stk_limit",
        "suspend_d",
        "cyq_perf",
        "margin",
        "limit_list_d",
        "limit_list_ths",
        "limit_step",
        "limit_cpt_list",
        "top_list",
        "block_trade",
        "stock_st",
        "stk_nineturn",
        "stk_period_bar_week",
        "stk_period_bar_month",
        "stk_period_bar_adj_week",
        "stk_period_bar_adj_month",
        "broker_recommend",
    },
    "market_fund": {"fund_daily", "fund_adj"},
    "index_series": {"index_daily", "index_daily_basic", "index_basic", "etf_index", "index_weight"},
    "board_hotspot": {
        "ths_index",
        "dc_index",
        "dc_member",
        "ths_member",
        "ths_daily",
        "dc_daily",
        "ths_hot",
        "dc_hot",
        "kpl_list",
        "kpl_concept_cons",
    },
    "moneyflow": {
        "moneyflow",
        "moneyflow_ths",
        "moneyflow_dc",
        "moneyflow_cnt_ths",
        "moneyflow_ind_ths",
        "moneyflow_ind_dc",
        "moneyflow_mkt_dc",
    },
    "reference_master": {"trade_cal", "hk_basic", "us_basic", "etf_basic"},
    "low_frequency": {"dividend", "stk_holdernumber"},
}

REQUIRED_BUILDERS = {
    "input_schema": "build_input_schema",
    "planning_spec": "build_planning_spec",
    "normalization_spec": "build_normalization_spec",
    "write_spec": "build_write_spec",
}

DISALLOWED_DIRECT_CONSTRUCTORS = {
    "InputSchema",
    "PlanningSpec",
    "NormalizationSpec",
    "WriteSpec",
}


def _module_path(domain: str) -> Path:
    return CONTRACTS_ROOT / f"{domain}.py"


def _parse_module(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_registry_domain_contract_files_are_fixed_and_complete() -> None:
    actual = {path.stem for path in CONTRACTS_ROOT.glob("*.py") if path.name != "__init__.py"}
    assert actual == EXPECTED_DOMAIN_FILES


def test_domain_contract_keys_match_guardrail_matrix() -> None:
    assert set(DOMAIN_CONTRACT_GROUPS.keys()) == EXPECTED_DOMAIN_FILES

    for domain, expected_keys in EXPECTED_DOMAIN_KEYS.items():
        actual_keys = set(DOMAIN_CONTRACT_GROUPS[domain].keys())
        assert actual_keys == expected_keys, (
            f"domain={domain} 的 CONTRACTS key 漂移。"
            "如确需新增/迁移数据集，请先更新 registry 开发指南并同步本门禁矩阵。"
        )

    expected_all = set().union(*EXPECTED_DOMAIN_KEYS.values())
    assert set(SYNC_V2_CONTRACTS.keys()) == expected_all


def test_contract_modules_must_use_builder_templates_for_schema_specs() -> None:
    for domain in EXPECTED_DOMAIN_FILES:
        module_path = _module_path(domain)
        module_ast = _parse_module(module_path)
        contract_calls = [
            node
            for node in ast.walk(module_ast)
            if isinstance(node, ast.Call) and _call_name(node.func) == "DatasetSyncContract"
        ]

        for call in contract_calls:
            keyword_values = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            for keyword, expected_builder in REQUIRED_BUILDERS.items():
                value = keyword_values.get(keyword)
                assert isinstance(value, ast.Call), (
                    f"{domain}: DatasetSyncContract.{keyword} 必须通过 {expected_builder}(...) 构造"
                )
                assert _call_name(value.func) == expected_builder, (
                    f"{domain}: DatasetSyncContract.{keyword} 必须使用 {expected_builder}(...)，"
                    "禁止直接构造 schema/spec 对象。"
                )

        called_names = {
            name
            for node in ast.walk(module_ast)
            if isinstance(node, ast.Call) and (name := _call_name(node.func)) is not None
        }
        leaked = sorted(DISALLOWED_DIRECT_CONSTRUCTORS.intersection(called_names))
        assert not leaked, (
            f"{domain}: 检测到直接构造 {leaked}。"
            "请改用 builders（build_input_schema/build_planning_spec/"
            "build_normalization_spec/build_write_spec）。"
        )
