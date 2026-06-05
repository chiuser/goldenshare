from __future__ import annotations

from typing import Any

import requests

from src.foundation.config.settings import get_settings


class ClickHouseReadonlyClient:
    """Minimal HTTP client for bounded read-only Wealth market facts."""

    def __init__(self, *, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def query_json(self, query: str) -> list[dict[str, Any]]:
        settings = get_settings()
        timeout_seconds = settings.wealth_clickhouse_timeout_seconds
        params: dict[str, str] = {
            "database": settings.wealth_clickhouse_database,
            "user": settings.wealth_clickhouse_user,
            "default_format": "JSON",
            "max_execution_time": str(timeout_seconds),
            "timeout_before_checking_execution_speed": "0",
            "max_rows_to_read": "100000",
            "max_bytes_to_read": "100000000",
            "max_result_rows": "1000",
            "result_overflow_mode": "break",
            "readonly": "1",
        }
        if settings.wealth_clickhouse_password:
            params["password"] = settings.wealth_clickhouse_password

        response = self._session.post(
            settings.wealth_clickhouse_url,
            params=params,
            data=query.encode("utf-8"),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("ClickHouse JSON response missing data list")
        return data
