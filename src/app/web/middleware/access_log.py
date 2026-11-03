from __future__ import annotations

from time import monotonic, perf_counter

from starlette.middleware.base import BaseHTTPMiddleware

from src.app.web.logging import get_web_logger
from .stock_daily_kline import is_stock_daily_kline


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        if not is_stock_daily_kline(scope):
            return await super().__call__(scope, receive, send)
        start = monotonic()
        state = scope.setdefault("state", {})
        state.setdefault("stock_daily_arrived_at", start)
        status = None

        async def forward(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, forward)
        finally:
            get_web_logger().info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%s",
                state.get("request_id"), scope["method"], scope["path"], status,
                round((monotonic() - start) * 1000, 2),
            )

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        start = perf_counter()
        response = await call_next(request)
        duration_ms = round((perf_counter() - start) * 1000, 2)
        logger = get_web_logger()
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%s",
            getattr(request.state, "request_id", None),
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
