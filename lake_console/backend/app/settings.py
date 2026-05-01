from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LakeConsoleConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LakeConsoleSettings:
    lake_root: Path
    tushare_token: str | None
    host: str = "127.0.0.1"
    port: int = 8010
    bucket_count: int = 32
    target_part_size_mb: int = 256
    tushare_request_limit_per_minute: int = 500
    stk_mins_request_window_days: int = 31


def load_settings(*, lake_root: str | None = None, require_lake_root: bool = True) -> LakeConsoleSettings:
    config_file = _load_config_file()
    configured_root = lake_root or os.getenv("GOLDENSHARE_LAKE_ROOT") or _config_str(config_file, "lake_root")
    if not configured_root:
        configured_root = None
    if configured_root is None and require_lake_root:
        raise LakeConsoleConfigError(
            "缺少 GOLDENSHARE_LAKE_ROOT。请通过 --lake-root、环境变量或 lake_console/config.local.toml 指定移动盘 Lake 根目录。"
        )
    root = Path(configured_root).expanduser().resolve() if configured_root else Path(".").resolve()
    return LakeConsoleSettings(
        lake_root=root,
        tushare_token=os.getenv("TUSHARE_TOKEN") or _config_str(config_file, "tushare_token"),
        host=os.getenv("LAKE_CONSOLE_HOST") or _config_str(config_file, "host") or "127.0.0.1",
        port=int(os.getenv("LAKE_CONSOLE_PORT") or _config_int(config_file, "port") or 8010),
        bucket_count=int(os.getenv("LAKE_STK_MINS_BUCKET_COUNT") or _config_int(config_file, "bucket_count") or 32),
        target_part_size_mb=int(
            os.getenv("LAKE_STK_MINS_TARGET_PART_SIZE_MB") or _config_int(config_file, "target_part_size_mb") or 256
        ),
        tushare_request_limit_per_minute=int(
            os.getenv("LAKE_TUSHARE_REQUEST_LIMIT_PER_MINUTE")
            or _config_int(config_file, "tushare_request_limit_per_minute")
            or 500
        ),
        stk_mins_request_window_days=int(
            os.getenv("LAKE_STK_MINS_REQUEST_WINDOW_DAYS")
            or _config_int(config_file, "stk_mins_request_window_days")
            or 31
        ),
    )


def _load_config_file() -> dict[str, Any]:
    config_path = Path("lake_console/config.local.toml")
    if not config_path.exists():
        return {}
    with config_path.open("rb") as file:
        payload = tomllib.load(file)
    return payload


def _config_str(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LakeConsoleConfigError(f"lake_console/config.local.toml 中 {key} 必须是字符串。")
    return value or None


def _config_int(config: dict[str, Any], key: str) -> int | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise LakeConsoleConfigError(f"lake_console/config.local.toml 中 {key} 必须是整数。")
    return value
