"""Stock daily API dependency contract; the App composition root supplies the backend."""

from typing import Protocol

from starlette.responses import Response

from src.biz.services.wealth.market.stock_detail.stock_daily_kline_contracts import (
    StockDailyKlineRequest,
)


class StockDailyKlineBackend(Protocol):
    def response(self, request: StockDailyKlineRequest, *, arrived_at: float) -> Response: ...


def get_stock_daily_kline_backend() -> StockDailyKlineBackend:
    raise RuntimeError("Stock daily kline backend is not installed")
