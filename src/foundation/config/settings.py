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
    tushare_enable_us_hot_markets: bool = Field(default=False, alias="TUSHARE_ENABLE_US_HOT_MARKETS")
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
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    realtime_stock_rt_daily_enabled: bool = Field(default=False, alias="REALTIME_STOCK_RT_DAILY_ENABLED")
    realtime_stock_rt_daily_poll_interval_seconds: int = Field(
        default=6,
        alias="REALTIME_STOCK_RT_DAILY_POLL_INTERVAL_SECONDS",
    )
    realtime_stock_rt_daily_collection_sessions: str = Field(
        default="09:30-11:30,13:00-15:00",
        alias="REALTIME_STOCK_RT_DAILY_COLLECTION_SESSIONS",
    )
    realtime_stock_rt_daily_max_calls_per_minute: int = Field(
        default=10,
        alias="REALTIME_STOCK_RT_DAILY_MAX_CALLS_PER_MINUTE",
    )
    realtime_stock_rt_daily_lease_ttl_seconds: int = Field(
        default=30,
        alias="REALTIME_STOCK_RT_DAILY_LEASE_TTL_SECONDS",
    )
    realtime_stock_rt_daily_stale_after_seconds: int = Field(
        default=20,
        alias="REALTIME_STOCK_RT_DAILY_STALE_AFTER_SECONDS",
    )
    realtime_stock_rt_daily_snapshot_ttl_seconds: int = Field(
        default=259200,
        alias="REALTIME_STOCK_RT_DAILY_SNAPSHOT_TTL_SECONDS",
    )
    realtime_stock_rt_daily_keep_recent_batches: int = Field(
        default=3,
        alias="REALTIME_STOCK_RT_DAILY_KEEP_RECENT_BATCHES",
    )
    realtime_stock_rt_daily_batch_stream_maxlen: int = Field(
        default=5000,
        alias="REALTIME_STOCK_RT_DAILY_BATCH_STREAM_MAXLEN",
    )
    realtime_stock_rt_daily_delta_stream_maxlen: int = Field(
        default=200000,
        alias="REALTIME_STOCK_RT_DAILY_DELTA_STREAM_MAXLEN",
    )
    realtime_stock_rt_daily_ts_code_pattern: str = Field(
        default="3*.SZ,6*.SH,0*.SZ,9*.BJ",
        alias="REALTIME_STOCK_RT_DAILY_TS_CODE_PATTERN",
    )
    realtime_stock_rt_min_enabled: bool = Field(default=False, alias="REALTIME_STOCK_RT_MIN_ENABLED")
    realtime_stock_rt_min_enabled_freqs: str = Field(
        default="1MIN,5MIN,15MIN,30MIN,60MIN",
        alias="REALTIME_STOCK_RT_MIN_ENABLED_FREQS",
    )
    realtime_stock_rt_min_poll_interval_seconds: int = Field(
        default=60,
        alias="REALTIME_STOCK_RT_MIN_POLL_INTERVAL_SECONDS",
    )
    realtime_stock_rt_min_collection_sessions: str = Field(
        default="09:30-11:30,13:00-15:00",
        alias="REALTIME_STOCK_RT_MIN_COLLECTION_SESSIONS",
    )
    realtime_stock_rt_min_max_calls_per_minute: int = Field(
        default=20,
        alias="REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE",
    )
    realtime_stock_rt_min_lease_ttl_seconds: int = Field(
        default=90,
        alias="REALTIME_STOCK_RT_MIN_LEASE_TTL_SECONDS",
    )
    realtime_stock_rt_min_stale_after_seconds: int = Field(
        default=90,
        alias="REALTIME_STOCK_RT_MIN_STALE_AFTER_SECONDS",
    )
    realtime_stock_rt_min_snapshot_ttl_seconds: int = Field(
        default=259200,
        alias="REALTIME_STOCK_RT_MIN_SNAPSHOT_TTL_SECONDS",
    )
    realtime_stock_rt_min_keep_recent_batches: int = Field(
        default=3,
        alias="REALTIME_STOCK_RT_MIN_KEEP_RECENT_BATCHES",
    )
    realtime_stock_rt_min_batch_stream_maxlen: int = Field(
        default=5000,
        alias="REALTIME_STOCK_RT_MIN_BATCH_STREAM_MAXLEN",
    )
    realtime_stock_rt_min_delta_stream_maxlen: int = Field(
        default=200000,
        alias="REALTIME_STOCK_RT_MIN_DELTA_STREAM_MAXLEN",
    )
    realtime_stock_rt_min_ts_code_pattern: str = Field(
        default="3*.SZ,6*.SH,0*.SZ,9*.BJ",
        alias="REALTIME_STOCK_RT_MIN_TS_CODE_PATTERN",
    )
    realtime_stock_rt_min_source_timeout_seconds: int = Field(
        default=20,
        alias="REALTIME_STOCK_RT_MIN_SOURCE_TIMEOUT_SECONDS",
    )
    ops_task_completion_worker_poll_seconds: int = Field(
        default=5,
        alias="OPS_TASK_COMPLETION_WORKER_POLL_SECONDS",
    )
    ops_task_completion_worker_batch_size: int = Field(
        default=20,
        alias="OPS_TASK_COMPLETION_WORKER_BATCH_SIZE",
    )
    ops_task_notify_feishu_enabled: bool = Field(default=False, alias="OPS_TASK_NOTIFY_FEISHU_ENABLED")
    goldenshare_feishu_webhook_url: str = Field(default="", alias="GOLDENSHARE_FEISHU_WEBHOOK_URL")
    goldenshare_feishu_webhook_secret: str = Field(default="", alias="GOLDENSHARE_FEISHU_WEBHOOK_SECRET")
    ops_task_notify_timeout_seconds: int = Field(default=5, alias="OPS_TASK_NOTIFY_TIMEOUT_SECONDS")
    ops_public_base_url: str = Field(default="", alias="OPS_PUBLIC_BASE_URL")
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
