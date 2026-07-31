from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.foundation.config.settings import Settings


SUPPORTED_MINUTE_FREQS = (1, 5, 15, 30, 60, 90, 120)


class LocalMinuteCapabilityError(RuntimeError):
    """Raised when the explicitly enabled local minute capability is unusable."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LocalMinuteCapability:
    enabled: bool
    lake_root: Path | None
    reason_code: str | None


def resolve_local_minute_capability(settings: Settings) -> LocalMinuteCapability:
    """Resolve local-only minute API availability without importing business modules."""

    environment = (settings.app_env or os.getenv("APP_ENV", "")).strip().lower()
    if environment not in {"dev", "local"} or not settings.wealth_local_lake_minute_api_enabled:
        return LocalMinuteCapability(enabled=False, lake_root=None, reason_code=None)

    raw_root = settings.goldenshare_lake_root.strip()
    if not raw_root:
        raise LocalMinuteCapabilityError(
            code="SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地分钟能力已开启，但 GOLDENSHARE_LAKE_ROOT 未配置。",
        )

    lake_root = Path(raw_root).expanduser().resolve()
    if not lake_root.is_dir() or not os.access(lake_root, os.R_OK):
        raise LocalMinuteCapabilityError(
            code="SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地分钟能力已开启，但配置的 Lake root 不可读。",
        )

    try:
        import duckdb  # noqa: F401
    except Exception as exc:
        raise LocalMinuteCapabilityError(
            code="SM_LOCAL_LAKE_NOT_CONFIGURED",
            message="本地分钟能力已开启，但未安装 local-lake DuckDB 依赖。",
        ) from exc

    return LocalMinuteCapability(enabled=True, lake_root=lake_root, reason_code=None)
