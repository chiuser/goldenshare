from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from src.web.api.router import router as api_router
from src.web.exceptions import install_exception_handlers
from src.web.lifespan import web_lifespan
from src.web.middleware import AccessLogMiddleware, RequestIdMiddleware
from src.web.settings import STATIC_DIR, get_web_settings


settings = get_web_settings()

app = FastAPI(
    title="Goldenshare Web",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=web_lifespan,
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(AccessLogMiddleware)
if settings.web_cors_origins.strip():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.web_cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="web-static")
install_exception_handlers(app)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
def root():  # type: ignore[no-untyped-def]
    if settings.platform_check_enabled:
        return RedirectResponse(url="/platform-check")
    return RedirectResponse(url="/api/docs")


@app.get("/platform-check", include_in_schema=False)
def platform_check():  # type: ignore[no-untyped-def]
    if not settings.platform_check_enabled:
        return RedirectResponse(url="/api/docs")
    return FileResponse(Path(STATIC_DIR) / "platform-check.html")
