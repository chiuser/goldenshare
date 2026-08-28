from __future__ import annotations

import ast
from pathlib import Path
import re

from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXCEPTION_REGISTRY = REPO_ROOT / "wealth/docs/system/exception-code-registry.md"
IMPLEMENTATION_DESIGN = (
    REPO_ROOT
    / "wealth/docs/pages/wealth-exploration/sector-analysis-implementation-design-v1.md"
)
LOW_LEVEL_DESIGN = (
    REPO_ROOT
    / "wealth/docs/pages/wealth-exploration/sector-analysis-low-level-design-v1.md"
)
ALEMBIC_VERSIONS = REPO_ROOT / "alembic/versions"

APPROVED_SOURCE_TABLES = {
    "core_serving.trade_calendar",
    "core_serving.wealth_sector_hierarchy",
    "core_serving.dc_daily",
    "core_serving.dc_member",
    "core_serving.equity_daily_bar",
}
APPROVED_MODEL_MODULES = {
    "src.foundation.models.core.dc_daily",
    "src.foundation.models.core.trade_calendar",
    "src.foundation.models.core_serving.dc_member",
    "src.foundation.models.core_serving.equity_daily_bar",
    "src.foundation.models.core_serving.wealth_sector_hierarchy",
}
APPROVED_SHARED_QUERY_MODULES = {
    "src.biz.queries.wealth.market.common.sector_hierarchy_query",
    "src.biz.queries.wealth.market.context.market_page_context_query",
}
REGISTERED_EXCEPTION_CODES = {
    "SA_FACT_VERSION_MISMATCH",
    "SA_SOURCE_DELAYED",
    "SA_SOURCE_EMPTY",
    "SA_HIERARCHY_UNAVAILABLE",
    "SA_SCOPE_INVALID",
    "SA_SELECTION_INVALID",
    "SA_MEMBER_FACT_MISMATCH",
    "SA_MEMBER_SOURCE_EMPTY",
    "SA_MEMBER_QUERY_FAILED",
    "SA_QUERY_FAILED",
}

DUAL_MOMENTUM_BACKEND_PATHS = (
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_analysis_meta_query_service.py",
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_momentum_snapshot_query_service.py",
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_dual_momentum_query_service.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_dual_momentum_contract.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_dual_momentum_classifier.py",
    REPO_ROOT / "src/biz/schemas/wealth/market/sector_dual_momentum.py",
)
DUAL_MOMENTUM_FORBIDDEN_TOKENS = (
    "dc_member",
    "equity_daily_bar",
    "member_detail",
    "moneyflow",
    "sector_heat",
    "qtf",
    "dagster",
    "duckdb",
    "parquet",
    "prediction",
    "forecast",
    "success_rate",
)

BACKEND_SECTOR_ANALYSIS_PATHS = (
    REPO_ROOT / "src/biz/api/wealth/market/sector_analysis.py",
    REPO_ROOT / "src/biz/schemas/wealth/market/sector_analysis.py",
    REPO_ROOT / "src/biz/queries/wealth/market/sector_analysis",
    REPO_ROOT / "src/biz/services/wealth/market/sector_analysis",
)
SHARED_QUERY_PATHS = (
    REPO_ROOT / "src/biz/queries/wealth/market/context/market_page_context_query.py",
    REPO_ROOT / "src/biz/queries/wealth/market/common/sector_hierarchy_query.py",
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_overview/sector_hierarchy_query.py",
)
FRONTEND_SECTOR_ANALYSIS_PATHS = (
    REPO_ROOT / "wealth/src/pages/wealth-exploration/SectorAnalysisPage.tsx",
    REPO_ROOT / "wealth/src/features/wealth-exploration/sector-analysis",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "qtf",
    "lake_console",
    "orchestrator",
    "dagster",
    "src.ops",
    "src.operations",
    "src.foundation.ingestion",
)
FORBIDDEN_SCOPE_TOKENS = (
    "dc_index",
    "moneyflow",
    "sector_heat",
    "sw2021",
    "shenwan",
    "backtest",
    "prediction",
    "predictive",
    "forecast",
    "success_rate",
    "turn_hot",
    "tushare",
    "duckdb",
    "parquet",
)
WRITE_TOKENS = (
    "mapped_column",
    "__tablename__",
    "sqlalchemy.insert",
    "sqlalchemy.update",
    "sqlalchemy.delete",
    "redis",
    "celery",
)


def _iter_files(paths: tuple[Path, ...], *, suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix in suffixes:
            files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file() and candidate.suffix in suffixes
            )
    return sorted(set(files))


def _python_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.lineno, node.module))
    return imports


def _python_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _target_sources() -> dict[Path, str]:
    paths = _iter_files(
        BACKEND_SECTOR_ANALYSIS_PATHS + FRONTEND_SECTOR_ANALYSIS_PATHS,
        suffixes=(".py", ".ts", ".tsx"),
    )
    return {path: path.read_text(encoding="utf-8") for path in paths}


def test_sector_analysis_source_table_contract_is_exactly_five_prod_tables() -> None:
    actual_tables = {
        TradeCalendar.__table__.fullname,
        WealthSectorHierarchy.__table__.fullname,
        DcDaily.__table__.fullname,
        DcMember.__table__.fullname,
        EquityDailyBar.__table__.fullname,
    }

    assert actual_tables == APPROVED_SOURCE_TABLES


def test_sector_analysis_backend_only_imports_approved_fact_models_and_shared_queries() -> (
    None
):
    python_files = _iter_files(
        BACKEND_SECTOR_ANALYSIS_PATHS + SHARED_QUERY_PATHS,
        suffixes=(".py",),
    )
    violations: list[str] = []

    for path in python_files:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        for line_no, module in _python_imports(path):
            if (
                module.startswith("src.foundation.models")
                and module not in APPROVED_MODEL_MODULES
            ):
                violations.append(
                    f"{relative_path}:{line_no} imports unapproved model {module}"
                )
            if module.startswith("src.biz.queries.wealth.market"):
                is_local_sector_analysis = module.startswith(
                    "src.biz.queries.wealth.market.sector_analysis"
                )
                if (
                    not is_local_sector_analysis
                    and module not in APPROVED_SHARED_QUERY_MODULES
                ):
                    violations.append(
                        f"{relative_path}:{line_no} imports unapproved query {module}"
                    )

    assert not violations, (
        "板块分析只能读取冻结的五张 Prod 表和两项共享查询：\n" + "\n".join(violations)
    )


def test_sector_analysis_has_no_forbidden_subsystem_or_persistence_dependency() -> None:
    violations: list[str] = []
    backend_files = _iter_files(BACKEND_SECTOR_ANALYSIS_PATHS, suffixes=(".py",))

    for path in backend_files:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        for line_no, module in _python_imports(path):
            if any(
                _matches_prefix(module, prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(
                    f"{relative_path}:{line_no} imports forbidden subsystem {module}"
                )
        for token in WRITE_TOKENS:
            if token in lowered:
                violations.append(f"{relative_path} contains persistence token {token}")
        explicit_tables = {
            table
            for literal in _python_string_literals(path)
            for table in re.findall(
                r"\b(?:core_serving|core|raw|raw_tushare)\.[a-z][a-z0-9_]*\b",
                literal.lower(),
            )
        }
        for table in sorted(explicit_tables - APPROVED_SOURCE_TABLES):
            violations.append(
                f"{relative_path} references unapproved source table {table}"
            )

    assert not violations, (
        "板块分析不得接入 QTF/DG/Lake、写入链路或第六张来源表：\n"
        + "\n".join(violations)
    )


def test_sector_analysis_scope_does_not_expand_to_unapproved_research_or_datasets() -> (
    None
):
    violations: list[str] = []
    for path, source in _target_sources().items():
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        lowered = source.lower()
        for token in FORBIDDEN_SCOPE_TOKENS:
            if token in lowered:
                violations.append(
                    f"{relative_path} contains unapproved scope token {token}"
                )

    assert not violations, "板块分析首期只能实现行业横截面动量事实：\n" + "\n".join(
        violations
    )


def test_sector_analysis_exception_codes_match_the_central_registry() -> None:
    registry = EXCEPTION_REGISTRY.read_text(encoding="utf-8")
    registered = set(
        re.findall(
            r"^\| `(SA_[A-Z0-9_]+)` \| `sectorAnalysis` \|",
            registry,
            flags=re.MULTILINE,
        )
    )

    assert registered == REGISTERED_EXCEPTION_CODES
    assert "`PARTIAL` 只作为交易日来源覆盖元数据，不是页面状态或异常码" in registry
    assert "显式 PARTIAL 日期仍使用 READY 骨架" in registry
    assert "显式日期 `expectedAvailability=MISSING`" in registry
    assert "`calculableCount=0`" in registry

    for document in (IMPLEMENTATION_DESIGN, LOW_LEVEL_DESIGN):
        documented = set(
            re.findall(r"\bSA_[A-Z0-9_]+\b", document.read_text(encoding="utf-8"))
        )
        assert documented == REGISTERED_EXCEPTION_CODES

    used_codes = set(
        re.findall(r"\bSA_[A-Z0-9_]+\b", "\n".join(_target_sources().values()))
    )
    assert used_codes <= REGISTERED_EXCEPTION_CODES


def test_sector_analysis_does_not_add_an_alembic_migration() -> None:
    violations: list[str] = []
    for path in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        if "sector_analysis" in source or "sector-analysis" in source:
            violations.append(path.relative_to(REPO_ROOT).as_posix())

    assert not violations, "板块分析首期不允许新增迁移：\n" + "\n".join(violations)


def test_dual_momentum_backend_stays_on_the_three_read_only_fact_sources() -> None:
    violations: list[str] = []
    for path in DUAL_MOMENTUM_BACKEND_PATHS:
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        lowered = source.lower()
        for token in DUAL_MOMENTUM_FORBIDDEN_TOKENS:
            if token in lowered:
                violations.append(f"{relative_path} contains forbidden token {token}")
        for line_no, module in _python_imports(path):
            if module.startswith("src.foundation.models") and module not in {
                "src.foundation.models.core.dc_daily",
                "src.foundation.models.core.trade_calendar",
                "src.foundation.models.core_serving.wealth_sector_hierarchy",
            }:
                violations.append(
                    f"{relative_path}:{line_no} imports unapproved dual source {module}"
                )

    assert not violations, (
        "双动量只允许复用交易日历、行业层级和行业日行情：\n"
        + "\n".join(violations)
    )


def test_dual_momentum_adds_only_the_two_frozen_read_only_routes() -> None:
    api_source = (
        REPO_ROOT / "src/biz/api/wealth/market/sector_analysis.py"
    ).read_text(encoding="utf-8")

    assert api_source.count('@router.get(\n    "/dual-momentum/') == 2
    assert '"/dual-momentum/meta"' in api_source
    assert '"/dual-momentum/results"' in api_source
    assert '@router.post(\n    "/dual-momentum/' not in api_source
