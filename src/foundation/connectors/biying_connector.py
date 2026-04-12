from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.foundation.connectors.base import SourceConnector
from src.foundation.config.settings import get_settings


class BiyingSourceConnector(SourceConnector):
    source_key = "biying"

    def __init__(self, token: str | None = None, base_url: str | None = None, timeout: int | tuple[int, int] = (5, 30)) -> None:
        settings = get_settings()
        self.token = token or settings.biying_token
        self.base_url = (base_url or settings.biying_base_url).rstrip("/")
        self.timeout = timeout if isinstance(timeout, tuple) else (5, timeout)
        self.session = self._build_session()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _build_session(self) -> Session:
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            other=3,
            backoff_factor=0.5,
            backoff_jitter=0.2,
            status=0,
            allowed_methods=None,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=20,
            pool_maxsize=20,
        )
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def supports_api(self, api_name: str) -> bool:
        return api_name == "stock_basic"

    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        del params, fields
        if not self.supports_api(api_name):
            raise ValueError(f"Biying source does not support api_name={api_name}")
        if not self.token:
            raise ValueError("BIYING_TOKEN is empty")

        endpoint = f"{self.base_url}/hslt/list/{self.token}"
        response = self.session.get(endpoint, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Biying API response format invalid: expected list")
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
        return rows
