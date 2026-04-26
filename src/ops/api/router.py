from fastapi import APIRouter

from src.ops.api import (
    catalog,
    codebook,
    dataset_pipeline_modes,
    freshness,
    layer_snapshots,
    manual_actions,
    overview,
    review_center,
    probes,
    resolution_releases,
    runtime,
    schedules,
    source_management_bridge,
    std_rules,
    task_runs,
)


router = APIRouter()
router.include_router(overview.router)
router.include_router(freshness.router)
router.include_router(schedules.router)
router.include_router(probes.router)
router.include_router(resolution_releases.router)
router.include_router(std_rules.router)
router.include_router(layer_snapshots.router)
router.include_router(source_management_bridge.router)
router.include_router(runtime.router)
router.include_router(catalog.router)
router.include_router(manual_actions.router)
router.include_router(dataset_pipeline_modes.router)
router.include_router(review_center.router)
router.include_router(codebook.router)
router.include_router(task_runs.router)

__all__ = ["router"]
