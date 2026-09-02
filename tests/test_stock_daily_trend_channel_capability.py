from __future__ import annotations

import importlib.util
import importlib
from pathlib import Path

import pytest
from fastapi import APIRouter

from src.foundation.config.settings import Settings
from src.foundation.config.stock_daily_trend_channel_capability import (
    StockDailyTrendChannelCapability,
    resolve_stock_daily_trend_channel_capability,
)


def _settings(*, app_env: str, enabled: bool, lake_root: Path | None) -> Settings:
    return Settings(
        APP_ENV=app_env,
        GOLDENSHARE_LAKE_ROOT=str(lake_root or ""),
        WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED=enabled,
    )


def _ready_roots(root: Path) -> None:
    (root / "gold/indicator/stock_daily_trend_channel").mkdir(parents=True)
    (root / "gold/indicator/stock_daily_trend_channel_state").mkdir(parents=True)


def test_remote_capability_is_disabled_without_duckdb_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_checked(name: str):
        if name == "duckdb":
            pytest.fail("remote capability must not probe DuckDB")
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fail_if_checked)
    capability = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="prod", enabled=True, lake_root=None)
    )

    assert capability == StockDailyTrendChannelCapability(False, None, None)


def test_local_capability_requires_flag_formal_root_duckdb_and_both_datasets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.foundation.config.stock_daily_trend_channel_capability.FORMAL_LAKE_ROOT",
        tmp_path,
    )
    disabled = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="local", enabled=False, lake_root=tmp_path)
    )
    assert disabled.enabled is False

    missing = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="local", enabled=True, lake_root=tmp_path)
    )
    assert missing.enabled is False
    assert missing.reason_code == "STOCK_TREND_CHANNEL_SOURCE_NOT_READY"

    _ready_roots(tmp_path)
    ready = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="local", enabled=True, lake_root=tmp_path)
    )
    assert ready.enabled is True
    assert ready.lake_root == tmp_path.resolve()


def test_local_capability_rejects_non_formal_root_and_missing_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formal_root = tmp_path / "formal"
    other_root = tmp_path / "other"
    _ready_roots(formal_root)
    _ready_roots(other_root)
    monkeypatch.setattr(
        "src.foundation.config.stock_daily_trend_channel_capability.FORMAL_LAKE_ROOT",
        formal_root,
    )

    wrong_root = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="local", enabled=True, lake_root=other_root)
    )
    assert wrong_root.enabled is False
    assert wrong_root.reason_code == "STOCK_TREND_CHANNEL_SOURCE_NOT_READY"

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    missing_duckdb = resolve_stock_daily_trend_channel_capability(
        _settings(app_env="dev", enabled=True, lake_root=formal_root)
    )
    assert missing_duckdb.enabled is False
    assert missing_duckdb.reason_code == "STOCK_TREND_CHANNEL_SOURCE_NOT_READY"


def test_router_composition_is_independent_from_minute_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_router = importlib.import_module("src.app.api.v1.router")
    target = APIRouter()
    monkeypatch.setattr(
        app_router,
        "resolve_stock_daily_trend_channel_capability",
        lambda _settings: StockDailyTrendChannelCapability(False, None, None),
    )
    app_router._include_local_stock_daily_trend_channel_router(target)
    assert target.routes == []

    monkeypatch.setattr(
        app_router,
        "resolve_stock_daily_trend_channel_capability",
        lambda _settings: StockDailyTrendChannelCapability(
            True,
            Path("/Volumes/datasource/data_lake"),
            None,
        ),
    )
    app_router._include_local_stock_daily_trend_channel_router(target)
    assert [route.path for route in target.routes] == [
        "/wealth/market/stock-detail/trend-channel"
    ]
