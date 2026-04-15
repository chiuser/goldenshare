from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any
from urllib.parse import urlencode

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
        return api_name in {"stock_basic", "equity_daily_bar", "moneyflow"}

    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.supports_api(api_name):
            raise ValueError(f"Biying source does not support api_name={api_name}")
        if not self.token:
            raise ValueError("BIYING_TOKEN is empty")

        if api_name == "stock_basic":
            return self._call_stock_basic()
        if api_name == "equity_daily_bar":
            return self._call_equity_daily_bar(params=params)
        return self._call_moneyflow(params=params)

    def _call_stock_basic(self) -> list[dict[str, Any]]:
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

    def _call_equity_daily_bar(self, *, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = params or {}
        dm = str(payload.get("dm") or "").strip().upper()
        if not dm:
            raise ValueError("dm is required for biying equity_daily_bar")
        freq = str(payload.get("freq") or "d").strip().lower()
        adj_type = str(payload.get("adj_type") or "f").strip().lower()
        if freq != "d":
            raise ValueError("Only daily freq=d is supported for biying equity_daily_bar")
        if adj_type not in {"n", "f", "b", "fr", "br"}:
            raise ValueError("adj_type must be one of n/f/b/fr/br")

        query: dict[str, str] = {}
        start = payload.get("st")
        end = payload.get("et")
        limit = payload.get("lt")
        if start:
            query["st"] = str(start)
        if end:
            query["et"] = str(end)
        if limit:
            query["lt"] = str(limit)
        query_text = f"?{urlencode(query)}" if query else ""

        endpoint = f"{self.base_url}/hsstock/history/{dm}/{freq}/{adj_type}/{self.token}{query_text}"
        response = self.session.get(endpoint, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            error_message = str(data.get("error") or "").strip()
            if "数据不存在" in error_message:
                self.logger.info(
                    "Biying equity_daily_bar no data dm=%s adj_type=%s st=%s et=%s",
                    dm,
                    adj_type,
                    query.get("st"),
                    query.get("et"),
                )
                return []
        if not isinstance(data, list):
            raise RuntimeError("Biying equity_daily_bar response format invalid: expected list")
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _call_moneyflow(self, *, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = params or {}
        dm = str(payload.get("dm") or "").strip().upper()
        if not dm:
            raise ValueError("dm is required for biying moneyflow")

        query: dict[str, str] = {}
        start = payload.get("st")
        end = payload.get("et")
        limit = payload.get("lt")
        if start:
            query["st"] = str(start)
        if end:
            query["et"] = str(end)
        if limit:
            query["lt"] = str(limit)
        query_text = f"?{urlencode(query)}" if query else ""

        endpoint = f"{self.base_url}/hsstock/history/transaction/{dm}/{self.token}{query_text}"
        response = self.session.get(endpoint, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            error_message = str(data.get("error") or "").strip()
            if "数据不存在" in error_message:
                self.logger.info(
                    "Biying moneyflow no data dm=%s st=%s et=%s",
                    dm,
                    query.get("st"),
                    query.get("et"),
                )
                return []
        if not isinstance(data, list):
            raise RuntimeError("Biying moneyflow response format invalid: expected list")
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
        return rows
