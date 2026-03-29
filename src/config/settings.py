from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/goldenshare",
        alias="DATABASE_URL",
    )
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")
    tushare_base_url: str = Field(default="https://api.tushare.pro", alias="TUSHARE_BASE_URL")
    default_exchange: str = Field(default="SSE", alias="DEFAULT_EXCHANGE")
    sync_batch_size: int = Field(default=1000, alias="SYNC_BATCH_SIZE")
    history_start_date: str = Field(default="2000-01-01", alias="HISTORY_START_DATE")
    tushare_max_calls_per_minute: int = Field(default=280, alias="TUSHARE_MAX_CALLS_PER_MINUTE")
    web_host: str = Field(default="127.0.0.1", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    web_debug: bool = Field(default=False, alias="WEB_DEBUG")
    web_log_level: str = Field(default="INFO", alias="WEB_LOG_LEVEL")
    web_cors_origins: str = Field(default="", alias="WEB_CORS_ORIGINS")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=480, alias="JWT_EXPIRE_MINUTES")
    platform_check_enabled: bool = Field(default=True, alias="PLATFORM_CHECK_ENABLED")

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = os.environ.get("GOLDENSHARE_ENV_FILE", ".env").strip() or ".env"
    return Settings(_env_file=env_file, _env_file_encoding="utf-8")
