"""Two-field DG configuration extraction; existing readers are intentionally untouched."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .download_errors import DownloadErrorCode, require

DEFAULT_BASE_URL = "https://api.tushare.pro"


def read_tushare_connection(environ: Mapping[str, str]) -> tuple[str, str]:
    # Source: PeriodHttpConfig.from_environment's no-override branch, lines 65-77.
    # Do not call the old class: it would also read the retired rate setting.
    token = environ.get("TUSHARE_TOKEN", "").strip()
    base_url = environ.get("TUSHARE_BASE_URL", DEFAULT_BASE_URL).strip()
    _validate_connection(token, base_url)
    return token, base_url


def _validate_connection(token, base_url):
    valid = False
    try:
        url = urlsplit(base_url)
        valid = bool(
            token
            and url.scheme in ("http", "https")
            and url.netloc
            and url.hostname
            and not url.username
            and not url.password
        )
        _ = url.port
    except ValueError:
        valid = False
    require(valid, DownloadErrorCode.CONFIGURATION)


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    token: str = field(repr=False)
    base_url: str = field(repr=False)
    unit_memory_limit_bytes: int = 2147483648
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    request_timeout_seconds: float = 45.0
    max_retries: int = 3
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0)
    poll_interval_seconds: float = 0.1
    max_request_bytes: int = 1048576
    max_response_bytes: int = 67108864
    working_reserve_bytes: int = 134217728
    sort_block_records: int = 4096

    def __post_init__(self):
        code = DownloadErrorCode.CONFIGURATION
        _validate_connection(self.token, self.base_url)
        positive_ints = (
            "unit_memory_limit_bytes",
            "max_request_bytes",
            "max_response_bytes",
            "working_reserve_bytes",
            "sort_block_records",
        )
        for name in positive_ints:
            require(type(getattr(self, name)) is int and getattr(self, name) > 0, code)
        require(type(self.max_retries) is int and self.max_retries >= 0, code)
        for name in (
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "request_timeout_seconds",
            "poll_interval_seconds",
        ):
            value = getattr(self, name)
            require(
                type(value) in (float, int) and math.isfinite(value) and value > 0, code
            )
        require(
            type(self.retry_backoff_seconds) is tuple
            and len(self.retry_backoff_seconds) == self.max_retries,
            code,
        )
        require(
            all(
                type(x) in (int, float) and math.isfinite(x) and x >= 0
                for x in self.retry_backoff_seconds
            ),
            code,
        )
        require(
            max(self.connect_timeout_seconds, self.read_timeout_seconds)
            <= self.request_timeout_seconds,
            code,
        )
        require(
            self.poll_interval_seconds
            < min(self.connect_timeout_seconds, self.read_timeout_seconds),
            code,
        )
        require(self.working_reserve_bytes < self.unit_memory_limit_bytes, code)
        require(
            self.max_request_bytes
            <= self.unit_memory_limit_bytes - self.working_reserve_bytes,
            code,
        )


class ConfigurationLoader:
    @staticmethod
    def load_configuration() -> ConfigurationSnapshot:
        token, base_url = read_tushare_connection(os.environ)
        return ConfigurationSnapshot(token=token, base_url=base_url)
