from src.services.sync.registry import SYNC_SERVICE_REGISTRY


def test_registry_contains_required_resources() -> None:
    assert "stock_basic" in SYNC_SERVICE_REGISTRY
    assert "daily" in SYNC_SERVICE_REGISTRY
    assert "fund_daily" in SYNC_SERVICE_REGISTRY
    assert "stk_period_bar_week" in SYNC_SERVICE_REGISTRY
    assert "index_weight" in SYNC_SERVICE_REGISTRY
