from __future__ import annotations

from fastapi import FastAPI

from lake_console.backend.app.api import datasets, health, lake_status, partitions


def create_app() -> FastAPI:
    app = FastAPI(title="Goldenshare Lake Console", version="0.1.0")
    app.include_router(health.router)
    app.include_router(lake_status.router)
    app.include_router(datasets.router)
    app.include_router(partitions.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    from lake_console.backend.app.settings import load_settings

    settings = load_settings(require_lake_root=False)
    uvicorn.run("lake_console.backend.app.main:app", host=settings.host, port=settings.port, reload=False)
