from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

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
    biying_token: str = Field(default="", alias="BIYING_TOKEN")
    biying_base_url: str = Field(default="https://api.biyingapi.com", alias="BIYING_BASE_URL")
    biying_max_calls_per_minute: int = Field(default=280, alias="BIYING_MAX_CALLS_PER_MINUTE")
    default_exchange: str = Field(default="SSE", alias="DEFAULT_EXCHANGE")
    sync_batch_size: int = Field(default=1000, alias="SYNC_BATCH_SIZE")
    history_start_date: str = Field(default="2000-01-01", alias="HISTORY_START_DATE")
    tushare_max_calls_per_minute: int = Field(default=280, alias="TUSHARE_MAX_CALLS_PER_MINUTE")
    web_host: str = Field(default="127.0.0.1", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    web_debug: bool = Field(default=False, alias="WEB_DEBUG")
    web_log_level: str = Field(default="INFO", alias="WEB_LOG_LEVEL")
    web_cors_origins: str = Field(default="", alias="WEB_CORS_ORIGINS")
    frontend_dev_server_url: str = Field(default="", alias="FRONTEND_DEV_SERVER_URL")
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=480, alias="JWT_EXPIRE_MINUTES")
    auth_register_mode: str = Field(default="closed", alias="AUTH_REGISTER_MODE")
    auth_default_role: str = Field(default="viewer", alias="AUTH_DEFAULT_ROLE")
    auth_require_email_verification: bool = Field(default=True, alias="AUTH_REQUIRE_EMAIL_VERIFICATION")
    auth_refresh_token_expire_days: int = Field(default=14, alias="AUTH_REFRESH_TOKEN_EXPIRE_DAYS")
    auth_verify_email_expire_minutes: int = Field(default=1440, alias="AUTH_VERIFY_EMAIL_EXPIRE_MINUTES")
    auth_reset_password_expire_minutes: int = Field(default=30, alias="AUTH_RESET_PASSWORD_EXPIRE_MINUTES")
    auth_login_max_failures: int = Field(default=5, alias="AUTH_LOGIN_MAX_FAILURES")
    auth_lock_minutes: int = Field(default=15, alias="AUTH_LOCK_MINUTES")
    auth_password_min_length: int = Field(default=8, alias="AUTH_PASSWORD_MIN_LENGTH")
    auth_debug_expose_action_token: bool = Field(default=False, alias="AUTH_DEBUG_EXPOSE_ACTION_TOKEN")
    platform_check_enabled: bool = Field(default=True, alias="PLATFORM_CHECK_ENABLED")
    quote_api_auth_required: bool = Field(default=False, alias="QUOTE_API_AUTH_REQUIRED")
    biz_use_serving_light: bool = Field(default=True, alias="BIZ_USE_SERVING_LIGHT")
    biz_serving_fallback: bool = Field(default=True, alias="BIZ_SERVING_FALLBACK")
    sync_v2_strict_contract: bool = Field(default=True, alias="SYNC_V2_STRICT_CONTRACT")

    model_config = SettingsConfigDict(extra="ignore")


def _load_env_file_values(env_file: str) -> dict[str, str]:
    path = Path(env_file)
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = os.environ.get("GOLDENSHARE_ENV_FILE", ".env").strip() or ".env"
    env_values = _load_env_file_values(env_file)
    keyword_values: dict[str, str] = {}
    overridden_env: dict[str, str] = {}
    for field_name, field in Settings.model_fields.items():
        alias = field.alias or field_name
        if alias in env_values:
            keyword_values[alias] = env_values[alias]
            if alias in os.environ:
                overridden_env[alias] = os.environ.pop(alias)
    try:
        return Settings(_env_file=None, **keyword_values)
    finally:
        os.environ.update(overridden_env)
