from __future__ import annotations

import ast
from pathlib import Path

from src.foundation.datasets.definitions import (
    BOARD_HOTSPOT_ROWS,
    INDEX_SERIES_ROWS,
    LOW_FREQUENCY_ROWS,
    MARKET_EQUITY_ROWS,
    MARKET_FUND_ROWS,
    MONEYFLOW_ROWS,
    NEWS_ROWS,
    REFERENCE_MASTER_ROWS,
    list_defined_datasets,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_ROOT = REPO_ROOT / "src/foundation/datasets/definitions"
SRC_ROOT = REPO_ROOT / "src"

EXPECTED_DOMAIN_FILES = {
    "market_equity",
    "market_fund",
    "index_series",
    "board_hotspot",
    "moneyflow",
    "news",
    "reference_master",
    "low_frequency",
}

EXPECTED_DOMAIN_KEYS: dict[str, set[str]] = {
    "market_equity": {
        "biying_equity_daily",
        "daily",
        "adj_factor",
        "daily_basic",
        "stk_limit",
        "stk_mins",
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
        "stk_factor_pro",
        "stk_period_bar_week",
        "stk_period_bar_month",
        "stk_period_bar_adj_week",
        "stk_period_bar_adj_month",
        "broker_recommend",
    },
    "market_fund": {"fund_daily", "fund_adj"},
    "index_series": {
        "index_daily",
        "index_weekly",
        "index_monthly",
        "index_daily_basic",
        "index_basic",
        "etf_index",
        "index_weight",
    },
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
        "biying_moneyflow",
        "moneyflow",
        "moneyflow_ths",
        "moneyflow_dc",
        "moneyflow_cnt_ths",
        "moneyflow_ind_ths",
        "moneyflow_ind_dc",
        "moneyflow_mkt_dc",
    },
    "reference_master": {"trade_cal", "stock_basic", "hk_basic", "us_basic", "etf_basic"},
    "low_frequency": {"dividend", "stk_holdernumber"},
    "news": {"cctv_news"},
}

LEGACY_ROUTE_TOGGLE_TOKENS = (
    "USE_" + "SYNC" + "_V2_DATASETS",
    "use_" + "sync" + "_v2_datasets",
)


def _parse_module(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_definition_domain_files_are_fixed_and_complete() -> None:
    actual = {path.stem for path in DEFINITIONS_ROOT.glob("*.py") if path.name != "__init__.py" and not path.name.startswith("_")}
    assert actual == EXPECTED_DOMAIN_FILES


def test_definition_domain_keys_match_guardrail_matrix() -> None:
    actual_by_domain: dict[str, set[str]] = {
        "market_equity": {row["identity"]["dataset_key"] for row in MARKET_EQUITY_ROWS},
        "market_fund": {row["identity"]["dataset_key"] for row in MARKET_FUND_ROWS},
        "index_series": {row["identity"]["dataset_key"] for row in INDEX_SERIES_ROWS},
        "board_hotspot": {row["identity"]["dataset_key"] for row in BOARD_HOTSPOT_ROWS},
        "moneyflow": {row["identity"]["dataset_key"] for row in MONEYFLOW_ROWS},
        "news": {row["identity"]["dataset_key"] for row in NEWS_ROWS},
        "reference_master": {row["identity"]["dataset_key"] for row in REFERENCE_MASTER_ROWS},
        "low_frequency": {row["identity"]["dataset_key"] for row in LOW_FREQUENCY_ROWS},
    }
    assert set(actual_by_domain) == EXPECTED_DOMAIN_FILES
    for domain, expected_keys in EXPECTED_DOMAIN_KEYS.items():
        assert actual_by_domain[domain] == expected_keys

    expected_all = set().union(*EXPECTED_DOMAIN_KEYS.values())
    assert {definition.dataset_key for definition in list_defined_datasets()} == expected_all


def test_definition_modules_do_not_import_legacy_runtime_package() -> None:
    violations: list[str] = []
    for path in sorted(DEFINITIONS_ROOT.glob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        module_ast = _parse_module(path)
        for node in ast.walk(module_ast):
            if isinstance(node, ast.ImportFrom) and node.module and ("sync" + "_v2") in node.module:
                violations.append(f"{path.name}:{node.lineno}: {node.module}")
    assert not violations, "DatasetDefinition 模块不得再依赖旧执行包:\n" + "\n".join(violations)


def test_no_legacy_dataset_route_toggle_in_src_runtime() -> None:
    violations: list[str] = []
    for file_path in sorted(SRC_ROOT.rglob("*.py")):
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            for token in LEGACY_ROUTE_TOGGLE_TOKENS:
                if token in line:
                    violations.append(f"{rel_path}:{lineno}: {line.strip()}")

    assert not violations, (
        "检测到已废弃的 V2 路由开关引用（USE_SYNC_V2_DATASETS）。"
        "当前运行只允许新维护主链:\n" + "\n".join(violations)
    )
