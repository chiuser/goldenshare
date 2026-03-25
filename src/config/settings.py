from __future__ import annotations

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
