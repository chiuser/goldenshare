from fastapi import APIRouter

from src.ops.api import (
    catalog,
    dataset_pipeline_modes,
    executions,
    freshness,
    layer_snapshots,
    overview,
    probes,
    resolution_releases,
    runtime,
    schedules,
    source_management_bridge,
    std_rules,
)


router = APIRouter()
router.include_router(overview.router)
router.include_router(freshness.router)
router.include_router(schedules.router)
router.include_router(executions.router)
router.include_router(probes.router)
router.include_router(resolution_releases.router)
router.include_router(std_rules.router)
router.include_router(layer_snapshots.router)
router.include_router(source_management_bridge.router)
router.include_router(runtime.router)
router.include_router(catalog.router)
router.include_router(dataset_pipeline_modes.router)

__all__ = ["router"]
