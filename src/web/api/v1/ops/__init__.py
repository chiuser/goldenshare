from fastapi import APIRouter

from src.web.api.v1.ops import catalog, executions, freshness, overview, runtime, schedules


router = APIRouter()
router.include_router(overview.router)
router.include_router(freshness.router)
router.include_router(schedules.router)
router.include_router(executions.router)
router.include_router(runtime.router)
router.include_router(catalog.router)

__all__ = ["router"]
