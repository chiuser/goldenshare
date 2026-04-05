from __future__ import annotations

import os

from src.foundation.config.settings import get_settings
from src.db import get_engine, reset_db


def test_db_engine_uses_current_env_file(tmp_path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("DATABASE_URL=postgresql+psycopg://example_user:example_pass@example_host:5432/example_db\n")

    original_env_file = os.environ.get("GOLDENSHARE_ENV_FILE")
    try:
        os.environ["GOLDENSHARE_ENV_FILE"] = str(env_file)
        get_settings.cache_clear()
        reset_db()
        assert "example_host:5432/example_db" in str(get_engine().url)
    finally:
        if original_env_file is None:
            os.environ.pop("GOLDENSHARE_ENV_FILE", None)
        else:
            os.environ["GOLDENSHARE_ENV_FILE"] = original_env_file
        get_settings.cache_clear()
        reset_db()


def test_env_file_overrides_shell_database_url_when_explicit_env_file_is_set(tmp_path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("DATABASE_URL=postgresql+psycopg://remote_user:remote_pass@remote_host:5432/remote_db\n")

    original_env_file = os.environ.get("GOLDENSHARE_ENV_FILE")
    original_database_url = os.environ.get("DATABASE_URL")
    try:
        os.environ["GOLDENSHARE_ENV_FILE"] = str(env_file)
        os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:postgres@localhost:5432/goldenshare"
        get_settings.cache_clear()
        reset_db()

        settings = get_settings()
        assert "remote_host:5432/remote_db" in settings.database_url
        assert "remote_host:5432/remote_db" in str(get_engine().url)
    finally:
        if original_env_file is None:
            os.environ.pop("GOLDENSHARE_ENV_FILE", None)
        else:
            os.environ["GOLDENSHARE_ENV_FILE"] = original_env_file
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
        get_settings.cache_clear()
        reset_db()
