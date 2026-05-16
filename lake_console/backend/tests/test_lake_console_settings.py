from __future__ import annotations

from pathlib import Path

from lake_console.backend.app.settings import load_settings


def test_load_settings_reads_duckdb_compute_config(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "lake_console"
    config_dir.mkdir()
    lake_root = tmp_path / "lake"
    (config_dir / "config.local.toml").write_text(
        f"""
lake_root = "{lake_root}"
duckdb_threads = 6
duckdb_memory_limit = "20GB"
duckdb_temp_directory = "_tmp/duckdb-custom"
compute_bucket_count = 64
compute_max_active_writers = 1
compute_progress_interval_seconds = 3
compute_stale_heartbeat_seconds = 1200
compute_max_unit_retries = 2
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.lake_root == lake_root.resolve()
    assert settings.duckdb_threads == 6
    assert settings.duckdb_memory_limit == "20GB"
    assert settings.duckdb_temp_directory == "_tmp/duckdb-custom"
    assert settings.compute_bucket_count == 64
    assert settings.compute_max_active_writers == 1
    assert settings.compute_progress_interval_seconds == 3
    assert settings.compute_stale_heartbeat_seconds == 1200
    assert settings.compute_max_unit_retries == 2
