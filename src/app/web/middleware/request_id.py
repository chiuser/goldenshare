from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers, MutableHeaders

from .stock_daily_kline import is_stock_daily_kline


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        if not is_stock_daily_kline(scope):
            return await super().__call__(scope, receive, send)
        request_id = Headers(scope=scope).get("X-Request-ID") or str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def forward(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        await self.app(scope, receive, forward)

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
