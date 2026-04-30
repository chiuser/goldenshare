from __future__ import annotations

from lake_console.backend.app.settings import load_settings


def test_load_settings_reads_local_config_file(tmp_path, monkeypatch):
    config_dir = tmp_path / "lake_console"
    config_dir.mkdir()
    (config_dir / "config.local.toml").write_text(
        "\n".join(
            [
                'lake_root = "/Volumes/TestLake"',
                'tushare_token = "local-token"',
                'host = "127.0.0.2"',
                "port = 8011",
                "bucket_count = 64",
                "target_part_size_mb = 512",
                "tushare_request_limit_per_minute = 300",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOLDENSHARE_LAKE_ROOT", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    settings = load_settings()

    assert str(settings.lake_root) == "/Volumes/TestLake"
    assert settings.tushare_token == "local-token"
    assert settings.host == "127.0.0.2"
    assert settings.port == 8011
    assert settings.bucket_count == 64
    assert settings.target_part_size_mb == 512
    assert settings.tushare_request_limit_per_minute == 300


def test_environment_overrides_local_config_file(tmp_path, monkeypatch):
    config_dir = tmp_path / "lake_console"
    config_dir.mkdir()
    (config_dir / "config.local.toml").write_text(
        'lake_root = "/Volumes/TestLake"\ntushare_token = "local-token"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLDENSHARE_LAKE_ROOT", "/Volumes/EnvLake")
    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")

    settings = load_settings()

    assert str(settings.lake_root) == "/Volumes/EnvLake"
    assert settings.tushare_token == "env-token"
