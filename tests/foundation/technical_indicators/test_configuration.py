"""配置样本依据 LLD §16.1/§19.2 的已确认初始值及直接关系。"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError, MISSING, fields, replace

import pytest

from src.foundation.config.settings import Settings, get_settings
from src.foundation.technical_indicators.configuration import KernelConfig


# 预期字面值来自已冻结文档，不从待测类反向生成。
EXPECTED_DEFAULTS = {
    "max_concurrent_requests": 2,
    "max_waiting_requests": 2,
    "max_wait_ms": 2000,
    "sql_threads": 1,
    "batch_rows": 8192,
    "query_memory_bytes": 134217728,
    "request_memory_bytes": 268435456,
    "deployment_reserve_bytes": 1073741824,
    "total_target_ms": 8000,
    "cleanup_reserve_ms": 2000,
    "frontend_expire_ms": 10000,
    "max_input_rows": 1500000,
    "max_source_files": 10000,
    "max_output_rows": 10000,
    "max_output_bytes": 5000000,
    "max_indicator_instances": 16,
    "max_projected_row_group_bytes": 33554432,
    "control_poll_ms": 20,
    "monitor_join_target_ms": 200,
}


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    for name in EXPECTED_DEFAULTS:
        monkeypatch.delenv(f"TECHNICAL_INDICATOR_{name.upper()}", raising=False)
    monkeypatch.delenv("GOLDENSHARE_LAKE_ROOT", raising=False)
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(tmp_path / "missing.env"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def default_config() -> KernelConfig:
    return KernelConfig.from_settings(Settings(_env_file=None))


def test_all_confirmed_defaults_and_existing_lake_root_are_copied():
    settings = Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT="/not-opened/data_lake")
    config = KernelConfig.from_settings(settings)

    assert len(EXPECTED_DEFAULTS) == 19
    assert {
        name for name in Settings.model_fields if name.startswith("technical_indicator_")
    } == {f"technical_indicator_{name}" for name in EXPECTED_DEFAULTS}
    for name, expected in EXPECTED_DEFAULTS.items():
        field = Settings.model_fields[f"technical_indicator_{name}"]
        assert field.default == expected
        assert field.alias == f"TECHNICAL_INDICATOR_{name.upper()}"
        assert getattr(config, name) == expected
    assert config.goldenshare_lake_root == "/not-opened/data_lake"


def test_config_has_no_defaults_and_cannot_be_changed():
    assert all(field.default is MISSING for field in fields(KernelConfig))
    config = default_config()
    with pytest.raises(FrozenInstanceError):
        config.max_output_rows = 12
    with pytest.raises(TypeError):
        KernelConfig()


@pytest.mark.parametrize("name", tuple(EXPECTED_DEFAULTS))
def test_each_settings_field_can_be_changed(name):
    # 两倍初始值同时对total/cleanup保持合法；poll40仍小于cleanup2000。
    new_value = EXPECTED_DEFAULTS[name] * 2
    values = {f"TECHNICAL_INDICATOR_{name.upper()}": new_value}
    if name == "cleanup_reserve_ms":
        values["TECHNICAL_INDICATOR_TOTAL_TARGET_MS"] = 16000
    settings = Settings(_env_file=None, **values)

    assert getattr(KernelConfig.from_settings(settings), name) == new_value


@pytest.mark.parametrize("name", tuple(EXPECTED_DEFAULTS))
@pytest.mark.parametrize("invalid", [True, False, 1.5, "2", None])
def test_config_rejects_non_integer_and_bool_values(name, invalid):
    with pytest.raises(ValueError, match=name):
        replace(default_config(), **{name: invalid})


@pytest.mark.parametrize("name", tuple(EXPECTED_DEFAULTS))
def test_config_rejects_negative_values(name):
    with pytest.raises(ValueError, match=name):
        replace(default_config(), **{name: -1})


@pytest.mark.parametrize("name", tuple(n for n in EXPECTED_DEFAULTS if n != "max_waiting_requests"))
def test_config_requires_positive_values_except_waiting_count(name):
    with pytest.raises(ValueError, match=name):
        replace(default_config(), **{name: 0})


def test_zero_waiting_count_and_other_valid_direct_boundaries():
    config = replace(
        default_config(), max_waiting_requests=0, cleanup_reserve_ms=2,
        control_poll_ms=1, total_target_ms=3,
    )
    assert config.max_waiting_requests == 0
    assert config.cleanup_reserve_ms < config.total_target_ms
    assert config.control_poll_ms < config.cleanup_reserve_ms


@pytest.mark.parametrize("cleanup", [8000, 8001])
def test_cleanup_must_be_smaller_than_total(cleanup):
    with pytest.raises(ValueError, match="cleanup_reserve_ms"):
        replace(default_config(), cleanup_reserve_ms=cleanup)


@pytest.mark.parametrize("poll", [2000, 2001])
def test_poll_must_be_smaller_than_cleanup(poll):
    with pytest.raises(ValueError, match="control_poll_ms"):
        replace(default_config(), control_poll_ms=poll)


def test_no_unapproved_combination_or_period_limits_are_added():
    config = replace(
        default_config(), batch_rows=2000000, max_input_rows=1,
        query_memory_bytes=1024, request_memory_bytes=1,
        max_indicator_instances=20, max_output_rows=20000,
    )
    assert config.batch_rows == 2000000
    assert "max_period" not in {field.name for field in fields(config)}
    assert "max_source_bytes" not in {field.name for field in fields(config)}


def test_from_settings_does_not_read_environment_or_files(monkeypatch):
    settings = Settings(_env_file=None, GOLDENSHARE_LAKE_ROOT="/not-mounted/anywhere")
    monkeypatch.setenv("TECHNICAL_INDICATOR_BATCH_ROWS", "17")
    monkeypatch.setenv("GOLDENSHARE_LAKE_ROOT", "/different/root")
    config = KernelConfig.from_settings(settings)

    assert config.batch_rows == 8192
    assert config.goldenshare_lake_root == "/not-mounted/anywhere"
    settings.technical_indicator_batch_rows = 18
    assert config.batch_rows == 8192
    assert KernelConfig.from_settings(settings).batch_rows == 18


def test_env_file_precedes_environment_restores_it_and_cache_remains(monkeypatch, tmp_path):
    env_file = tmp_path / "kernel.env"
    env_file.write_text(
        "TECHNICAL_INDICATOR_BATCH_ROWS=31\nGOLDENSHARE_LAKE_ROOT=/declared/root\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(env_file))
    monkeypatch.setenv("TECHNICAL_INDICATOR_BATCH_ROWS", "17")
    monkeypatch.setenv("TECHNICAL_INDICATOR_SQL_THREADS", "3")
    monkeypatch.setenv("GOLDENSHARE_LAKE_ROOT", "/environment/root")

    first = get_settings()
    config = KernelConfig.from_settings(first)
    assert config.batch_rows == 31
    assert config.sql_threads == 3
    assert config.goldenshare_lake_root == "/declared/root"
    assert os.environ["TECHNICAL_INDICATOR_BATCH_ROWS"] == "17"
    assert os.environ["GOLDENSHARE_LAKE_ROOT"] == "/environment/root"

    env_file.write_text("TECHNICAL_INDICATOR_BATCH_ROWS=47\n", encoding="utf-8")
    assert get_settings() is first
    assert get_settings().technical_indicator_batch_rows == 31
    get_settings.cache_clear()
    assert get_settings().technical_indicator_batch_rows == 47
    assert config.batch_rows == 31


def test_invalid_parsed_configuration_raises_value_error():
    settings = Settings(_env_file=None, TECHNICAL_INDICATOR_MAX_WAITING_REQUESTS=-1)
    with pytest.raises(ValueError, match="max_waiting_requests"):
        KernelConfig.from_settings(settings)
