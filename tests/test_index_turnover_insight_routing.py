from __future__ import annotations

from pathlib import Path
import importlib

import pytest
from fastapi import APIRouter

from src.app.exceptions import WebAppError
from src.biz.api.wealth.market import index_turnover_insight as api
from src.foundation.config.local_minute_capability import LocalMinuteCapability


DISABLED = LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)
ENABLED = LocalMinuteCapability(
    enabled=True,
    lake_root=Path("/Volumes/datasource/data_lake"),
    reason_code=None,
)
app_router = importlib.import_module("src.app.api.v1.router")


def _disable_other_minute_routes(monkeypatch) -> None:
    monkeypatch.setattr(app_router, "resolve_local_minute_capability", lambda _settings: DISABLED)
    monkeypatch.setattr(
        app_router,
        "resolve_stock_nine_turn_minute_capability",
        lambda _settings: DISABLED,
    )
    monkeypatch.setattr(
        app_router,
        "resolve_index_nine_turn_minute_capability",
        lambda _settings: DISABLED,
    )


def test_index_batch_route_is_mounted_with_existing_index_capability(monkeypatch) -> None:
    _disable_other_minute_routes(monkeypatch)
    monkeypatch.setattr(
        app_router,
        "resolve_index_minute_capability",
        lambda _settings: ENABLED,
    )
    target = APIRouter()

    app_router._include_local_minute_router(target)

    paths = {route.path for route in target.routes}
    assert "/wealth/market/turnover-insight/indices" in paths
    assert "/wealth/market/index-detail/minutes" in paths


def test_index_batch_route_is_absent_when_capability_is_disabled(monkeypatch) -> None:
    _disable_other_minute_routes(monkeypatch)
    monkeypatch.setattr(
        app_router,
        "resolve_index_minute_capability",
        lambda _settings: DISABLED,
    )
    target = APIRouter()

    app_router._include_local_minute_router(target)

    assert target.routes == []


def test_mounted_route_recheck_failure_is_503_not_404(monkeypatch) -> None:
    monkeypatch.setattr(api, "resolve_index_minute_capability", lambda _settings: DISABLED)

    with pytest.raises(WebAppError) as captured:
        api._service()

    assert captured.value.status_code == 503
    assert captured.value.code == "ITI_SOURCE_NOT_READY"
