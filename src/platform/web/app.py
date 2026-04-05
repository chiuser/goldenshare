from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from src.platform.api.router import router as api_router
from src.platform.exceptions import install_exception_handlers
from src.platform.web.lifespan import web_lifespan
from src.platform.web.middleware import AccessLogMiddleware, RequestIdMiddleware
from src.platform.web.settings import FRONTEND_DIST_DIR, STATIC_DIR, get_web_settings


settings = get_web_settings()
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
FRONTEND_BRAND_DIR = FRONTEND_DIST_DIR / "brand"

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
if FRONTEND_ASSETS_DIR.exists():
    app.mount("/app/assets", StaticFiles(directory=str(FRONTEND_ASSETS_DIR)), name="frontend-assets")
if FRONTEND_BRAND_DIR.exists():
    app.mount("/app/brand", StaticFiles(directory=str(FRONTEND_BRAND_DIR)), name="frontend-brand")
install_exception_handlers(app)
app.include_router(api_router)


def _build_frontend_dev_url(path: str = "") -> str:
    base = settings.frontend_dev_server_url.strip().rstrip("/")
    suffix = f"/{path.lstrip('/')}" if path else ""
    return f"{base}/app{suffix}"


def _frontend_app_response(path: str = ""):  # type: ignore[no-untyped-def]
    if settings.frontend_dev_server_url.strip():
        return RedirectResponse(url=_build_frontend_dev_url(path))
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return PlainTextResponse(
        "Frontend app is not built yet. Run `cd frontend && npm install && npm run build` "
        "or configure FRONTEND_DEV_SERVER_URL for local development.",
        status_code=503,
    )


@app.get("/", include_in_schema=False)
def root():  # type: ignore[no-untyped-def]
    return RedirectResponse(url="/app")


@app.get("/platform-check", include_in_schema=False)
def platform_check():  # type: ignore[no-untyped-def]
    if not settings.platform_check_enabled:
        return RedirectResponse(url="/api/docs")
    return FileResponse(Path(STATIC_DIR) / "platform-check.html")


@app.get("/app", include_in_schema=False)
def frontend_app_root():  # type: ignore[no-untyped-def]
    return _frontend_app_response()


@app.get("/app/{subpath:path}", include_in_schema=False)
def frontend_app_subpath(subpath: str):  # type: ignore[no-untyped-def]
    if subpath.startswith("api/"):
        return RedirectResponse(url="/app")
    return _frontend_app_response(subpath)


@app.get("/ops", include_in_schema=False)
def operations_console():  # type: ignore[no-untyped-def]
    return RedirectResponse(url="/app/ops")


@app.get("/ops/{subpath:path}", include_in_schema=False)
def operations_console_subpath(subpath: str):  # type: ignore[no-untyped-def]
    if not subpath or subpath.startswith("api/"):
        return RedirectResponse(url="/app/ops")
    return RedirectResponse(url=f"/app/ops/{subpath}")
