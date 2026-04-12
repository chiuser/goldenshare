from __future__ import annotations

from types import SimpleNamespace

from src.foundation.serving.builders.registry import ServingBuilderRegistry
from src.foundation.serving.validation import validate_serving_coverage


class _DummyBuilder:
    def __init__(self, dataset_key: str) -> None:
        self.dataset_key = dataset_key

    def build_rows(self, **kwargs):  # pragma: no cover - protocol only
        return kwargs


def test_validate_serving_coverage_reports_missing_builder_and_target_dao() -> None:
    registry = ServingBuilderRegistry()
    # register only stock_basic
    registry.register(_DummyBuilder("stock_basic"))

    dao = SimpleNamespace(security=object())
    issues = validate_serving_coverage(dao=dao, builder_registry=registry)

    issue_types = {(item.dataset_key, item.issue_type) for item in issues}
    assert ("equity_daily_bar", "missing_builder") in issue_types
    assert ("equity_daily_bar", "missing_target_dao") in issue_types


def test_validate_serving_coverage_ok_when_all_required_present() -> None:
    registry = ServingBuilderRegistry()
    for dataset_key in (
        "stock_basic",
        "equity_daily_bar",
        "equity_adj_factor",
        "equity_daily_basic",
        "indicator_macd",
        "indicator_kdj",
        "indicator_rsi",
        "index_daily",
        "index_weekly",
        "index_monthly",
        "stk_period_bar_week",
        "stk_period_bar_month",
        "stk_period_bar_adj_week",
        "stk_period_bar_adj_month",
    ):
        registry.register(_DummyBuilder(dataset_key))

    dao = SimpleNamespace(
        security=object(),
        equity_daily_bar=object(),
        equity_adj_factor=object(),
        equity_daily_basic=object(),
        indicator_macd=object(),
        indicator_kdj=object(),
        indicator_rsi=object(),
        index_daily_serving=object(),
        index_weekly_serving=object(),
        index_monthly_serving=object(),
        stk_period_bar=object(),
        stk_period_bar_adj=object(),
    )
    issues = validate_serving_coverage(dao=dao, builder_registry=registry)
    assert issues == []
