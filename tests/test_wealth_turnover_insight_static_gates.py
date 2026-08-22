from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "src/biz"
QUERY_FILE = BACKEND_ROOT / "queries/wealth/market/turnover_insight/turnover_insight_query.py"
API_FILE = BACKEND_ROOT / "api/wealth/market/turnover_insight.py"
SCHEMA_FILE = BACKEND_ROOT / "schemas/wealth/market/turnover_insight.py"
FRONTEND_ROOT = REPO_ROOT / "wealth/src"
TURNOVER_FRONTEND_ROOT = FRONTEND_ROOT / "features/wealth-exploration/turnover-insight"
EXPLORATION_PAGE = FRONTEND_ROOT / "pages/wealth-exploration/WealthExplorationPage.tsx"
MARKET_OVERVIEW_PAGE = FRONTEND_ROOT / "pages/market-overview/MarketOverviewPage.tsx"


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

    for forbidden in ("reduce(", "/ 100000", "Math.round", "current - previous"):
        assert forbidden not in adapter_source
        assert forbidden not in controller_source
    for forbidden in ("dimension", "industry", "concept", "region"):
        assert forbidden not in request_source.lower()


def test_turnover_insight_frontend_has_one_page_slot_and_no_cross_feature_dependency() -> None:
    feature_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(TURNOVER_FRONTEND_ROOT.rglob("*.ts*"))
    )
    page_source = EXPLORATION_PAGE.read_text(encoding="utf-8")

    assert "features/market-overview" not in feature_source
    assert page_source.count('data-module-slot="sector-radar"') == 1
    assert page_source.index("<TurnoverInsightSection") < page_source.index('data-module-slot="sector-radar"')
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
    assert "readMarketContextRequest" in EXPLORATION_PAGE.read_text(encoding="utf-8")
    assert "readMarketContextRequest" in MARKET_OVERVIEW_PAGE.read_text(encoding="utf-8")
