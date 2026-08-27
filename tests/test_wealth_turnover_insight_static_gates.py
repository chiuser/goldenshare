from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "src/biz"
QUERY_FILE = BACKEND_ROOT / "queries/wealth/market/turnover_insight/turnover_insight_query.py"
COMMON_QUERY_FILE = BACKEND_ROOT / "queries/wealth/market/turnover_common/turnover_daily_average_query.py"
API_FILE = BACKEND_ROOT / "api/wealth/market/turnover_insight.py"
SCHEMA_FILE = BACKEND_ROOT / "schemas/wealth/market/turnover_insight.py"
FRONTEND_ROOT = REPO_ROOT / "wealth/src"
TURNOVER_FRONTEND_ROOT = FRONTEND_ROOT / "features/wealth-exploration/turnover-insight"
LANDING_PAGE = FRONTEND_ROOT / "pages/wealth-exploration/WealthExplorationLandingPage.tsx"
TURNOVER_PAGE = FRONTEND_ROOT / "pages/wealth-exploration/TurnoverInsightPage.tsx"
SECTOR_PAGE = FRONTEND_ROOT / "pages/wealth-exploration/SectorAnalysisPage.tsx"
EXPLORATION_SHELL_HOOK = (
    FRONTEND_ROOT / "pages/wealth-exploration/layout/useWealthExplorationShell.ts"
)
REMOVED_EXPLORATION_PAGE = (
    FRONTEND_ROOT / "pages/wealth-exploration/WealthExplorationPage.tsx"
)
MARKET_OVERVIEW_PAGE = FRONTEND_ROOT / "pages/market-overview/MarketOverviewPage.tsx"
MARKET_OVERVIEW_CSS = FRONTEND_ROOT / "pages/market-overview/market-overview-page.css"
SHARED_SHORTCUT_ROOT = FRONTEND_ROOT / "shared/ui/shortcut-bar"
REMOVED_MARKET_SHORTCUT = FRONTEND_ROOT / "features/market-overview/layout/ShortcutBar.tsx"


def _module_source() -> str:
    files = [
        *sorted((BACKEND_ROOT / "queries/wealth/market/turnover_insight").glob("*.py")),
        *sorted((BACKEND_ROOT / "services/wealth/market/turnover_insight").glob("*.py")),
        API_FILE,
        SCHEMA_FILE,
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_turnover_insight_uses_only_bounded_snapshot_and_calendar_query() -> None:
    source = _module_source()
    query_source = QUERY_FILE.read_text(encoding="utf-8")

    assert "WealthMarketTurnoverSnapshot.freq == 1" in query_source
    assert 'WealthMarketTurnoverSnapshot.build_status == "READY"' in query_source
    assert ".limit(_MAX_CANDIDATES)" in query_source
    assert "TradeCalendar" in query_source
    assert '"core.trade_calendar"' not in source
    assert "'core.trade_calendar'" not in source
    for forbidden in ("EquityDailyBar", "RawStkMins", "duckdb", "dagster", "data_lake"):
        assert forbidden not in source

    common_source = COMMON_QUERY_FILE.read_text(encoding="utf-8")
    assert "EquityDailyBar" in common_source
    assert "_AVERAGE_WINDOW_DAYS = 20" in common_source
    assert ".limit(_AVERAGE_WINDOW_DAYS)" in common_source
    assert ".group_by(EquityDailyBar.trade_date)" in common_source


def test_turnover_insight_does_not_reuse_old_turnover_domain_or_prediction_fields() -> None:
    source = _module_source()
    lowered = source.lower()

    assert ".market.turnover." not in source
    assert "TO_" not in source
    assert "forecast" not in lowered
    assert "predict" not in lowered


def test_turnover_insight_debug_gate_is_environment_bounded() -> None:
    source = API_FILE.read_text(encoding="utf-8")

    assert "debug: int = Query(default=0, ge=0, le=1)" in source
    assert '_DEBUG_ENVIRONMENTS = frozenset({"local", "dev", "test"})' in source
    assert "get_settings().app_env" in source


def test_turnover_insight_frontend_keeps_domain_math_on_the_backend() -> None:
    adapter_source = (
        TURNOVER_FRONTEND_ROOT / "api/turnoverInsightAdapter.ts"
    ).read_text(encoding="utf-8")
    controller_source = (
        TURNOVER_FRONTEND_ROOT / "model/useTurnoverInsightController.ts"
    ).read_text(encoding="utf-8")
    request_source = (
        TURNOVER_FRONTEND_ROOT / "api/turnoverInsightApi.ts"
    ).read_text(encoding="utf-8")

    for forbidden in ("reduce(", "/ 100000", "Math.round", "current - previous", "referenceLabel: `"):
        assert forbidden not in adapter_source
        assert forbidden not in controller_source
    for forbidden in ("dimension", "industry", "concept", "region"):
        assert forbidden not in request_source.lower()


def test_turnover_insight_frontend_has_one_owned_page_and_no_cross_feature_dependency() -> None:
    feature_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TURNOVER_FRONTEND_ROOT.rglob("*.ts*"))
    )
    turnover_page_source = TURNOVER_PAGE.read_text(encoding="utf-8")
    landing_page_source = LANDING_PAGE.read_text(encoding="utf-8")
    sector_page_source = SECTOR_PAGE.read_text(encoding="utf-8")

    assert "features/market-overview" not in feature_source
    assert turnover_page_source.count("<TurnoverInsightSection") == 1
    assert "TurnoverInsight" not in landing_page_source
    assert "SectorAnalysis" not in landing_page_source
    assert "TurnoverInsight" not in sector_page_source
    assert not REMOVED_EXPLORATION_PAGE.exists()
    assert "sector-radar" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in (LANDING_PAGE, TURNOVER_PAGE, SECTOR_PAGE)
    )
    assert "forecast" not in feature_source.lower()
    assert "predict" not in feature_source.lower()


def test_shared_frontend_moves_leave_no_compatibility_wrappers() -> None:
    removed_paths = (
        FRONTEND_ROOT / "features/market-overview/context/api/marketPageContextApi.ts",
        FRONTEND_ROOT / "features/market-overview/context/api/marketPageContextAdapter.ts",
        FRONTEND_ROOT / "features/market-overview/indices/api/marketMajorIndicesApi.ts",
        FRONTEND_ROOT / "features/market-overview/indices/api/marketMajorIndicesAdapter.ts",
        FRONTEND_ROOT / "features/market-overview/layout/Breadcrumb.tsx",
    )

    assert all(not path.exists() for path in removed_paths)
    assert not REMOVED_MARKET_SHORTCUT.exists()
    assert "readMarketContextRequest" in EXPLORATION_SHELL_HOOK.read_text(encoding="utf-8")
    assert "readMarketContextRequest" in MARKET_OVERVIEW_PAGE.read_text(encoding="utf-8")

    shared_shortcut_source = (SHARED_SHORTCUT_ROOT / "ShortcutCard.tsx").read_text(encoding="utf-8")
    shared_shortcut_css = (SHARED_SHORTCUT_ROOT / "shortcut-bar.css").read_text(encoding="utf-8")
    market_css = MARKET_OVERVIEW_CSS.read_text(encoding="utf-8")
    assert '<button' in shared_shortcut_source
    assert '<article' not in shared_shortcut_source
    for required in (
        "grid-template-columns: repeat(6, minmax(0, 1fr))",
        "gap: 10px",
        "min-height: 72px",
        "padding: 10px 11px",
        "appearance: none",
        "font: inherit",
        "width: 100%",
    ):
        assert required in shared_shortcut_css
    assert ".shortcut-bar" not in market_css
    assert ".shortcut-card" not in market_css
