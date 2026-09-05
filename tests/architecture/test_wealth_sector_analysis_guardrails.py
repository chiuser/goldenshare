from __future__ import annotations

import ast
from pathlib import Path
import re

from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
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
DAILY_FACTS_PATH = (
    REPO_ROOT / "src/biz/services/wealth/market/sector_analysis/daily_facts"
)
DAILY_FACTS_SOURCE_QUERY = DAILY_FACTS_PATH / "source_query.py"
DAILY_FACTS_WRITE_MODEL_PREFIX = "src.foundation.models.core_serving.wealth_sector_"

APPROVED_SOURCE_TABLES = {
    "core_serving.trade_calendar",
    "core_serving.wealth_sector_hierarchy",
    "core_serving.dc_daily",
    "core_serving.dc_member",
    "core_serving.equity_daily_bar",
    "core.equity_adj_factor",
}
APPROVED_MODEL_MODULES = {
    "src.foundation.models.core.dc_daily",
    "src.foundation.models.core.trade_calendar",
    "src.foundation.models.core_serving.dc_member",
    "src.foundation.models.core_serving.equity_daily_bar",
    "src.foundation.models.core_serving.equity_adj_factor",
    "src.foundation.models.core_serving.wealth_sector_hierarchy",
}
APPROVED_SERVING_FACT_MODEL_MODULES = {
    "src.foundation.models.core_serving.wealth_sector_analysis_publish_batch",
    "src.foundation.models.core_serving.wealth_sector_momentum_daily",
    "src.foundation.models.core_serving.wealth_sector_dual_momentum_daily",
    "src.foundation.models.core_serving.wealth_sector_relative_rotation_daily",
    "src.foundation.models.core_serving.wealth_sector_member_breadth_daily",
    "src.foundation.models.core_serving.wealth_sector_member_ma_breadth_daily",
    "src.foundation.models.core_serving.wealth_sector_price_volume_daily",
    "src.foundation.models.core_serving.wealth_sector_daily_insight_summary",
    "src.foundation.models.core_serving.wealth_sector_daily_insight_item",
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
    "SA_BREADTH_FACT_MISMATCH",
    "SA_BREADTH_SOURCE_EMPTY",
    "SA_BREADTH_QUERY_FAILED",
    "SA_PRICE_VOLUME_FACT_MISMATCH",
    "SA_DAILY_INSIGHT_BATCH_MISMATCH",
    "SA_DAILY_INSIGHT_QUERY_FAILED",
    "SA_DAILY_FACT_SOURCE_NOT_READY",
    "SA_DAILY_FACT_READBACK_MISMATCH",
    "SA_DAILY_FACT_PLAN_DRIFT",
    "SA_QUERY_FAILED",
}

DUAL_MOMENTUM_BACKEND_PATHS = (
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_analysis_fact_reader.py",
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
RELATIVE_ROTATION_BACKEND_PATHS = (
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_relative_rotation_query_service.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_contract.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_calculator.py",
    REPO_ROOT / "src/biz/schemas/wealth/market/sector_relative_rotation.py",
)
RELATIVE_ROTATION_FORBIDDEN_TOKENS = DUAL_MOMENTUM_FORBIDDEN_TOKENS + (
    "benchmark_index",
    "rs_ratio",
    "rs_momentum",
)
MEMBER_BREADTH_BACKEND_PATHS = (
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_member_breadth_query.py",
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_member_breadth_query_service.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_member_breadth_contract.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_member_breadth_calculator.py",
    REPO_ROOT / "src/biz/schemas/wealth/market/sector_member_breadth.py",
)
PRICE_VOLUME_BACKEND_PATHS = (
    REPO_ROOT
    / "src/biz/queries/wealth/market/sector_analysis/sector_price_volume_query_service.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_price_volume_contract.py",
    REPO_ROOT
    / "src/biz/services/wealth/market/sector_analysis/sector_price_volume_calculator.py",
    REPO_ROOT / "src/biz/schemas/wealth/market/sector_price_volume.py",
)
PRICE_VOLUME_APPROVED_MODEL_MODULES = {
    "src.foundation.models.core.dc_daily",
    "src.foundation.models.core.trade_calendar",
    "src.foundation.models.core_serving.wealth_sector_hierarchy",
}
PRICE_VOLUME_FORBIDDEN_TOKENS = (
    "dc_member",
    "equity_daily_bar",
    "equity_adj_factor",
    "moneyflow",
    "sector_heat",
    "qtf",
    "dagster",
    "duckdb",
    "parquet",
    "redis",
    "mapped_column",
    "__tablename__",
)
PRICE_VOLUME_FORBIDDEN_IMPORT_PREFIXES = (
    "src.foundation.config",
    "src.foundation.ingestion",
    "src.ops",
    "src.operations",
    "qtf",
    "lake_console",
    "orchestrator",
    "dagster",
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


def _is_daily_facts_file(path: Path) -> bool:
    return path == DAILY_FACTS_PATH or DAILY_FACTS_PATH in path.parents


def test_sector_analysis_source_table_contract_is_exactly_six_prod_tables() -> None:
    actual_tables = {
        TradeCalendar.__table__.fullname,
        WealthSectorHierarchy.__table__.fullname,
        DcDaily.__table__.fullname,
        DcMember.__table__.fullname,
        EquityDailyBar.__table__.fullname,
        EquityAdjFactor.__table__.fullname,
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
        if _is_daily_facts_file(path):
            continue
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        for line_no, module in _python_imports(path):
            if (
                module.startswith("src.foundation.models")
                and module
                not in APPROVED_MODEL_MODULES | APPROVED_SERVING_FACT_MODEL_MODULES
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
        "板块分析只能读取冻结来源、已发布 serving facts 和两项共享查询：\n"
        + "\n".join(violations)
    )


def test_m24_momentum_runtime_reads_published_facts_without_online_recalculation() -> None:
    service = (
        REPO_ROOT
        / "src/biz/queries/wealth/market/sector_analysis/sector_momentum_query_service.py"
    ).read_text(encoding="utf-8")
    reader = (
        REPO_ROOT
        / "src/biz/queries/wealth/market/sector_analysis/sector_analysis_fact_reader.py"
    ).read_text(encoding="utf-8")

    assert "SectorAnalysisFactReader" in service
    assert "sector_momentum_query import" not in service
    assert "SectorMomentumSnapshotQueryService" not in service
    assert "DcDaily" not in service
    assert "WealthSectorAnalysisPublishBatch" in reader
    assert "WealthSectorMomentumDaily" in reader
    assert "DcDaily" not in reader


def test_m24r_history_uses_compact_reader_without_full_ranking_rebuild() -> None:
    service = (
        REPO_ROOT
        / "src/biz/queries/wealth/market/sector_analysis/sector_momentum_query_service.py"
    ).read_text(encoding="utf-8")
    history_body = service.split("    def build_history(", maxsplit=1)[1].split(
        "    def _load_current_context(", maxsplit=1
    )[0]

    assert "load_momentum_history_slices" in history_body
    assert "load_momentum_rows" not in history_body
    assert "_ranked_from_published_rows" not in history_body
    assert "_published_rows_by_slice" not in service
    assert "_ranked_history_slice" not in service
    assert "_find_rank" not in service
    assert "SectorMomentumSnapshotQueryService" not in history_body
    assert "DcDaily" not in history_body


def test_sector_analysis_has_no_forbidden_subsystem_or_persistence_dependency() -> None:
    violations: list[str] = []
    backend_files = _iter_files(BACKEND_SECTOR_ANALYSIS_PATHS, suffixes=(".py",))

    for path in backend_files:
        if _is_daily_facts_file(path):
            continue
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
        "板块分析不得接入 QTF/DG/Lake、写入链路或第七张来源表：\n"
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


def test_sector_analysis_has_only_the_frozen_m22_migration() -> None:
    migrations: list[str] = []
    for path in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        if "sector_analysis" in source or "sector-analysis" in source:
            migrations.append(path.relative_to(REPO_ROOT).as_posix())

    assert migrations == [
        "alembic/versions/20260831_000168_add_wealth_sector_analysis_daily_facts.py"
    ]


def test_daily_facts_source_query_reads_only_the_frozen_six_sources() -> None:
    imports = {module for _, module in _python_imports(DAILY_FACTS_SOURCE_QUERY)}
    imported_models = {module for module in imports if module.startswith("src.foundation.models")}
    assert imported_models == APPROVED_MODEL_MODULES - {
        "src.foundation.models.core_serving.wealth_sector_hierarchy"
    }
    assert "src.biz.queries.wealth.market.common.sector_hierarchy_query" in imports
    source = DAILY_FACTS_SOURCE_QUERY.read_text(encoding="utf-8").lower()
    for forbidden in ("requests", "httpx", "dagster", "duckdb", "parquet", "moneyflow", "sector_heat", "qtf"):
        assert forbidden not in source
    assert "repeatable read, read only" in source


def test_daily_facts_persistence_is_isolated_to_its_repository() -> None:
    repository = DAILY_FACTS_PATH / "repository.py"
    violations: list[str] = []
    for path in _iter_files((DAILY_FACTS_PATH,), suffixes=(".py",)):
        imports = {module for _, module in _python_imports(path)}
        write_models = {
            module for module in imports if module.startswith(DAILY_FACTS_WRITE_MODEL_PREFIX)
        }
        if write_models and path != repository:
            violations.append(
                f"{path.relative_to(REPO_ROOT).as_posix()} imports write models {sorted(write_models)}"
            )
    assert not violations


def test_m25r_history_audit_cannot_reenter_full_preview_contract() -> None:
    planner = (DAILY_FACTS_PATH / "replay_planner.py").read_text(encoding="utf-8")
    auditor = (DAILY_FACTS_PATH / "history_input_auditor.py").read_text(
        encoding="utf-8"
    )
    executor = (
        REPO_ROOT / "src/app/runtime/sector_analysis_daily_task_executor.py"
    ).read_text(encoding="utf-8")

    assert "def preview_unit(" not in planner
    assert "def finalize(" not in planner
    for forbidden in (
        "preview_trade_date(",
        "._build(",
        "SectorAnalysisDailyFactBuilder",
        "SectorDailyInsightBuilder",
        "SectorAnalysisDailyFactsRepository",
    ):
        assert forbidden not in auditor
    history_audit_body = executor.split("    def audit_for_task_run(", maxsplit=1)[1].split(
        "    def execute_unit(", maxsplit=1
    )[0]
    assert "preview_trade_date(" not in history_audit_body
    assert "materialize_trade_date(" not in history_audit_body


def test_dual_momentum_backend_reads_only_published_serving_facts() -> None:
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
                "src.foundation.models.core.trade_calendar",
                "src.foundation.models.core_serving.wealth_sector_hierarchy",
            } | APPROVED_SERVING_FACT_MODEL_MODULES:
                violations.append(
                    f"{relative_path}:{line_no} imports unapproved dual source {module}"
                )

    assert not violations, (
        "双动量只允许读取交易日历、行业层级和已发布物化事实：\n" + "\n".join(violations)
    )
    service = (REPO_ROOT / "src/biz/queries/wealth/market/sector_analysis/sector_dual_momentum_query_service.py").read_text()
    for forbidden in ("SectorMomentumSnapshotQueryService", "SectorAnalysisMetaQueryService", "SectorDualMomentumClassifier", "calculate_for_date", "rank_strength", "DcDaily"):
        assert forbidden not in service


def test_dual_momentum_adds_only_the_two_frozen_read_only_routes() -> None:
    api_source = (REPO_ROOT / "src/biz/api/wealth/market/sector_analysis.py").read_text(
        encoding="utf-8"
    )

    assert api_source.count('@router.get(\n    "/dual-momentum/') == 2
    assert '"/dual-momentum/meta"' in api_source
    assert '"/dual-momentum/results"' in api_source
    assert '@router.post(\n    "/dual-momentum/' not in api_source


def test_relative_rotation_backend_reads_only_published_serving_facts() -> None:
    violations: list[str] = []
    for path in RELATIVE_ROTATION_BACKEND_PATHS:
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        lowered = source.lower()
        for token in RELATIVE_ROTATION_FORBIDDEN_TOKENS:
            if token in lowered:
                violations.append(f"{relative_path} contains forbidden token {token}")
        for line_no, module in _python_imports(path):
            if module.startswith("src.foundation.models") and module not in {
                "src.foundation.models.core.trade_calendar",
                "src.foundation.models.core_serving.wealth_sector_hierarchy",
            } | APPROVED_SERVING_FACT_MODEL_MODULES:
                violations.append(
                    f"{relative_path}:{line_no} imports unapproved rotation source {module}"
                )

    assert not violations, (
        "相对轮动只允许交易日历、行业层级和已发布物化事实：\n" + "\n".join(violations)
    )
    service = RELATIVE_ROTATION_BACKEND_PATHS[0].read_text()
    for forbidden in (
        "SectorMomentumSnapshotQueryService", "SectorAnalysisMetaQueryService",
        "SectorRelativeRotationCalculator", "SectorMomentumQuery", "calculate_for_date",
        "rank_strength", "rank_selected", "DcDaily", "load_open_dates",
    ):
        assert forbidden not in service


def test_relative_rotation_adds_only_the_two_frozen_read_only_routes() -> None:
    api_source = (REPO_ROOT / "src/biz/api/wealth/market/sector_analysis.py").read_text(
        encoding="utf-8"
    )

    assert api_source.count('@router.get(\n    "/relative-rotation/') == 2
    assert '"/relative-rotation/meta"' in api_source
    assert '"/relative-rotation/results"' in api_source
    assert '@router.post(\n    "/relative-rotation/' not in api_source


def test_member_breadth_adj_factor_is_isolated_to_its_query() -> None:
    breadth_query = MEMBER_BREADTH_BACKEND_PATHS[0]
    violations: list[str] = []
    for path in _iter_files(BACKEND_SECTOR_ANALYSIS_PATHS, suffixes=(".py",)):
        imported_modules = {module for _, module in _python_imports(path)}
        imports_factor = (
            "src.foundation.models.core_serving.equity_adj_factor" in imported_modules
        )
        if imports_factor and path not in {breadth_query, DAILY_FACTS_SOURCE_QUERY}:
            violations.append(
                f"{path.relative_to(REPO_ROOT).as_posix()} imports EquityAdjFactor"
            )
    assert not violations, "复权因子只能由成员广度 Query 读取：\n" + "\n".join(
        violations
    )


def test_member_breadth_adds_only_the_three_frozen_read_only_routes() -> None:
    api_source = (REPO_ROOT / "src/biz/api/wealth/market/sector_analysis.py").read_text(
        encoding="utf-8"
    )

    assert api_source.count('@router.get(\n    "/member-breadth/') == 3
    assert '"/member-breadth/meta"' in api_source
    assert '"/member-breadth/rankings"' in api_source
    assert '"/member-breadth/details"' in api_source
    assert '@router.post(\n    "/member-breadth/' not in api_source


def test_member_breadth_details_uses_one_projection_path_without_degradation() -> None:
    query_source = MEMBER_BREADTH_BACKEND_PATHS[0].read_text(encoding="utf-8")
    service_source = MEMBER_BREADTH_BACKEND_PATHS[1].read_text(encoding="utf-8")
    calculator_source = MEMBER_BREADTH_BACKEND_PATHS[3].read_text(encoding="utf-8")

    assert "def load_member_projection(" in query_source
    assert "DcMember.trade_date == target_date" in query_source
    assert "limit(ma_period)" in query_source
    assert "DcDaily" not in query_source
    assert "union_all" not in query_source
    assert "session.bind.dialect" not in query_source
    assert "from_statement(" not in query_source
    assert "def _build_members(" not in calculator_source
    assert "load_member_projection(" in service_source
    assert "load_breadth_rankings(" in service_source
    assert "load_breadth_history(" in service_source
    for obsolete in ("load_details_window(", "load_details_projection(", "load_window_relations(", "load_market_facts(", "rank_requested_metric(", "calculate_composition_grid("):
        assert obsolete not in service_source + query_source

    forbidden_degradation_tokens = (
        ".limit(625)",
        "top_n",
        "sample(",
        "history_range = 20",
        "redis",
    )
    assert not any(
        token in (query_source + service_source + calculator_source).lower()
        for token in forbidden_degradation_tokens
    )


def test_price_volume_backend_uses_published_facts_without_online_calculation() -> None:
    """M24.6.2 removes online raw queries; the offline formula is retained."""

    violations: list[str] = []
    for path in PRICE_VOLUME_BACKEND_PATHS:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        lowered = source.lower()
        for token in PRICE_VOLUME_FORBIDDEN_TOKENS:
            if token in lowered:
                violations.append(f"{relative_path} contains forbidden token {token}")
        for line_no, module in _python_imports(path):
            if (
                module.startswith("src.foundation.models")
                and module not in PRICE_VOLUME_APPROVED_MODEL_MODULES
            ):
                violations.append(
                    f"{relative_path}:{line_no} imports unapproved price-volume source {module}"
                )
            if any(
                _matches_prefix(module, prefix)
                for prefix in PRICE_VOLUME_FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(
                    f"{relative_path}:{line_no} imports forbidden subsystem/config {module}"
                )

    assert not violations, (
        "量价计算只允许读取交易日历、行业层级和行业日行情；日期仅复用共享发布覆盖，"
        "不得增加配置、缓存、写入或外部子系统依赖：\n" + "\n".join(violations)
    )

    query_path = (
        REPO_ROOT
        / "src/biz/queries/wealth/market/sector_analysis/sector_price_volume_query.py"
    )
    assert not query_path.exists()
    service = (
        REPO_ROOT
        / "src/biz/queries/wealth/market/sector_analysis/sector_price_volume_query_service.py"
    ).read_text()
    for removed in (
        "_valid_price_volume_predicate",
        "load_trade_date_coverage",
        "load_exact_trade_date_status",
        "SectorPriceVolumeQuery",
        "SectorPriceVolumeCalculator",
        "load_facts",
        "calculate_snapshot",
        "calculate_history",
    ):
        # The service class itself retains its public name.
        assert removed not in service.replace("SectorPriceVolumeQueryService", "")
    assert "load_momentum_coverage" in service
    assert "coverage.published_dates" in service
    assert 'availability == "COMPLETE"' not in service
