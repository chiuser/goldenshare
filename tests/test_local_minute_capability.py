from __future__ import annotations

import importlib.util

import pytest

from src.foundation.config.local_minute_capability import (
    LocalMinuteCapabilityError,
    resolve_local_minute_capability,
)
from src.foundation.config.settings import Settings


def _settings(*, app_env: str, enabled: bool, lake_root: str) -> Settings:
    return Settings(
        APP_ENV=app_env,
        WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=enabled,
        GOLDENSHARE_LAKE_ROOT=lake_root,
    )


def test_remote_profile_is_disabled_without_importing_duckdb(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_checked(name: str):
        if name == "duckdb":
            pytest.fail("remote capability must not inspect/import DuckDB")
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fail_if_checked)
    capability = resolve_local_minute_capability(_settings(app_env="prod", enabled=True, lake_root=""))

    assert capability.enabled is False
    assert capability.lake_root is None
    assert capability.reason_code is None


def test_local_disabled_profile_does_not_require_root() -> None:
    capability = resolve_local_minute_capability(_settings(app_env="dev", enabled=False, lake_root=""))

    assert capability.enabled is False
    assert capability.lake_root is None


def test_local_enabled_without_root_fails_fast() -> None:
    with pytest.raises(LocalMinuteCapabilityError) as exc_info:
        resolve_local_minute_capability(_settings(app_env="local", enabled=True, lake_root=""))

    assert exc_info.value.code == "SM_LOCAL_LAKE_NOT_CONFIGURED"


def test_local_enabled_with_unreadable_root_fails_fast(tmp_path) -> None:
    with pytest.raises(LocalMinuteCapabilityError) as exc_info:
        resolve_local_minute_capability(_settings(app_env="dev", enabled=True, lake_root=str(tmp_path / "missing")))

    assert exc_info.value.code == "SM_LOCAL_LAKE_NOT_CONFIGURED"


def test_local_enabled_with_readable_root_requires_optional_duckdb(tmp_path) -> None:
    if importlib.util.find_spec("duckdb") is None:
        pytest.skip("local-lake extra is not installed")

    capability = resolve_local_minute_capability(_settings(app_env="dev", enabled=True, lake_root=str(tmp_path)))

    assert capability.enabled is True
    assert capability.lake_root == tmp_path.resolve()
