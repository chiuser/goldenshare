from __future__ import annotations

from collections.abc import Sequence
import time
from typing import Any


DEFAULT_TUSHARE_REQUEST_LIMIT_PER_MINUTE = 500


class TushareQuotaExceededError(RuntimeError):
    def __init__(self, *, api_name: str, message: str) -> None:
        super().__init__(message)
        self.api_name = api_name
        self.message = message


class TushareLakeClient:
    def __init__(self, token: str | None, *, request_limit_per_minute: int = DEFAULT_TUSHARE_REQUEST_LIMIT_PER_MINUTE) -> None:
        if not token:
            raise RuntimeError("缺少 TUSHARE_TOKEN，无法请求 Tushare。")
        try:
            import tushare as ts
        except ModuleNotFoundError as exc:
            raise RuntimeError("缺少 tushare 依赖。请先安装 lake_console/backend/requirements.txt。") from exc
        self._pro = ts.pro_api(token)
        self._rate_limiter = TushareRateLimiter(request_limit_per_minute=request_limit_per_minute)

    def stock_basic(self, *, list_status: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        frame = self._request(
            self._pro.stock_basic,
            api_name="stock_basic",
            exchange="",
            list_status=list_status,
            fields=",".join(fields),
        )
        return _frame_to_rows(frame)

    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str | None,
        end_date: str | None,
        fields: Sequence[str],
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "exchange": exchange,
            "fields": ",".join(fields),
        }
        if start_date is not None:
            params["start_date"] = start_date
        if end_date is not None:
            params["end_date"] = end_date
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        frame = self._request(
            self._pro.trade_cal,
            api_name="trade_cal",
            **params,
        )
        return _frame_to_rows(frame)

    def index_basic(
        self,
        *,
        fields: Sequence[str],
        ts_code: str | None = None,
        name: str | None = None,
        market: str | None = None,
        publisher: str | None = None,
        category: str | None = None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        frame = self._request(
            self._pro.index_basic,
            api_name="index_basic",
            ts_code=ts_code,
            name=name,
            market=market,
            publisher=publisher,
            category=category,
            limit=limit,
            offset=offset,
            fields=",".join(fields),
        )
        return _frame_to_rows(frame)

    def stk_mins(
        self,
        *,
        ts_code: str,
        freq: int,
        start_date: str,
        end_date: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        frame = self._request(
            self._pro.stk_mins,
            api_name="stk_mins",
            ts_code=ts_code,
            freq=f"{freq}min",
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return _frame_to_rows(frame)

    def _request(self, method, *, api_name: str, **kwargs):  # type: ignore[no-untyped-def]
        self._rate_limiter.wait()
        try:
            return method(**kwargs)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if _is_quota_exceeded_message(message):
                raise TushareQuotaExceededError(api_name=api_name, message=message) from exc
            raise


class TushareRateLimiter:
    def __init__(
        self,
        *,
        request_limit_per_minute: int,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        if request_limit_per_minute <= 0:
            raise ValueError("tushare_request_limit_per_minute 必须大于 0。")
        self.interval_seconds = 60.0 / request_limit_per_minute
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at = now


def _frame_to_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        return [dict(row) for row in frame.to_dict(orient="records")]
    except AttributeError as exc:
        raise RuntimeError("Tushare 返回值不是可转换的 DataFrame。") from exc


def _is_quota_exceeded_message(message: str) -> bool:
    normalized = message.strip()
    return "频率超限" in normalized and "次/天" in normalized
