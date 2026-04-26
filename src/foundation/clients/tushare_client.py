from __future__ import annotations

from collections import deque
from collections.abc import Iterable
import logging
from threading import Lock
import time
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
import tushare as ts
from urllib3.util.retry import Retry

from src.foundation.config.settings import get_settings
from src.foundation.schemas import TushareEnvelope


class _RateLimiter:
    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls = max_calls_per_minute
        self.window_seconds = 60.0
        self.calls: deque[float] = deque()
        self.lock = Lock()

    def acquire(self) -> None:
        if self.max_calls <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.window_seconds:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                sleep_seconds = self.window_seconds - (now - self.calls[0]) + 0.05
            time.sleep(max(sleep_seconds, 0.05))


_API_RATE_LIMITS = {
    "stock_basic": 50,
    "index_daily": 500,
    "stk_mins": 1000,
}

_rate_limiters: dict[str, _RateLimiter] = {}


def _get_rate_limiter(api_name: str | None = None) -> _RateLimiter:
    settings = get_settings()
    key = api_name or "__default__"
    if key not in _rate_limiters:
        _rate_limiters[key] = _RateLimiter(_API_RATE_LIMITS.get(api_name or "", settings.tushare_max_calls_per_minute))
    return _rate_limiters[key]


class TushareHttpClient:
    def __init__(self, token: str | None = None, base_url: str | None = None, timeout: int | tuple[int, int] = (5, 30)) -> None:
        settings = get_settings()
        self.token = token or settings.tushare_token
        self.base_url = base_url or settings.tushare_base_url
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

    def _summarize_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        if not params:
            return {}
        keys = ("ts_code", "trade_date", "start_date", "end_date", "exchange")
        return {key: params[key] for key in keys if key in params}

    def _retry_count(self, response: requests.Response) -> int:
        retries = getattr(getattr(response, "raw", None), "retries", None)
        if retries is None:
            return 0
        history = getattr(retries, "history", ())
        return len(history)

    def call(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        _get_rate_limiter(api_name).acquire()
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": ",".join(fields) if fields else "",
        }
        param_summary = self._summarize_params(params)
        try:
            response = self.session.post(self.base_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            envelope = TushareEnvelope.model_validate(response.json())
        except requests.RequestException as exc:
            self.logger.warning(
                "Tushare request failed api_name=%s params=%s error=%s",
                api_name,
                param_summary,
                exc.__class__.__name__,
            )
            raise
        retry_count = self._retry_count(response)
        if retry_count:
            self.logger.info(
                "Tushare request succeeded after retry api_name=%s params=%s retry_count=%s",
                api_name,
                param_summary,
                retry_count,
            )
        if envelope.code != 0:
            raise RuntimeError(f"Tushare API error: {envelope.msg}")
        if envelope.data is None:
            return []
        return [dict(zip(envelope.data.fields, item, strict=False)) for item in envelope.data.items]


class TushareSdkClient:
    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        self.token = token or settings.tushare_token
        ts.set_token(self.token)

    def pro_bar(
        self,
        ts_code: str | None = None,
        asset: str = "E",
        start_date: str | None = None,
        end_date: str | None = None,
        adj: str | None = None,
        freq: str = "D",
    ) -> list[dict[str, Any]]:
        _get_rate_limiter("pro_bar").acquire()
        df = ts.pro_bar(ts_code=ts_code, asset=asset, start_date=start_date, end_date=end_date, adj=adj, freq=freq)
        if df is None:
            return []
        return df.to_dict(orient="records")
