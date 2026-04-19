from __future__ import annotations

from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware

from src.app.web.logging import get_web_logger


class AccessLogMiddleware(BaseHTTPMiddleware):
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
